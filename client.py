#!/usr/bin/env python3
"""Client HTTP du serveur de verrous, plus l'identité locale de la machine.

Le token Keychain identifie l'appareil ; il ne déverrouille rien. Le voler
ne donne pas le code, puisque c'est le serveur qui arbitre le temps.
"""

import json
import os
import secrets
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

KEYCHAIN_SERVICE = "com.utilities.prefs-token"
KEYCHAIN_ACCOUNT = "device"
STATE_PATH = Path.home() / "Library" / "Application Support" / "TempsDEcran" / "state.json"
def _baked_server() -> str | None:
    # Écrit à la compilation par setup.py. py2app pose RESOURCEPATH sur le
    # dossier Resources du bundle ; hors bundle, on cherche à côté de ce fichier.
    resources = os.environ.get("RESOURCEPATH")
    candidates = [Path(resources) / "server.txt"] if resources else []
    candidates.append(Path(__file__).with_name("server.txt"))
    for path in candidates:
        if path.exists():
            return path.read_text().strip() or None
    return None


def _default_server() -> str:
    # Surchargeable sans recompiler : la variable d'environnement l'emporte
    # sur le serveur gravé dans le bundle.
    return os.environ.get("TEMPS_DECRAN_SERVER") or _baked_server() or "https://screentime.mahwai.app"


class ServerUnreachable(Exception):
    pass


class ApiError(Exception):
    def __init__(self, status: int, detail):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.detail = detail


def server_url() -> str:
    return _state().get("server") or _default_server()


def _state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


_token_cache: str | None = None


def device_token() -> str:
    # Mémoïsé : l'attente d'un paiement interroge le serveur toutes les deux
    # secondes, et chaque appel au trousseau est un sous-processus.
    global _token_cache
    if _token_cache:
        return _token_cache

    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        _token_cache = result.stdout.strip()
        return _token_cache

    token = secrets.token_urlsafe(24)
    subprocess.run(
        ["security", "add-generic-password", "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE, "-w", token, "-U"],
        check=True,
        capture_output=True,
    )
    _token_cache = token
    return token


def _request(method: str, path: str, body: dict | None = None, timeout: int = 8) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        server_url() + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "X-Device-Token": device_token()},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        payload = json.loads(e.read() or b"{}")
        raise ApiError(e.code, payload.get("detail"))
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise ServerUnreachable(str(e))


def create_lock(minutes: int, amount_cents: int) -> dict:
    return _request("POST", "/locks", {"minutes": minutes, "amount_cents": amount_cents})


def current_lock() -> dict | None:
    lock = _request("GET", "/locks/current")["lock"]
    state = _state()
    state["lock_id"] = lock["lock_id"] if lock else None
    if lock:
        # Gardé après la révélation : un code payé puis fermé d'un clic de
        # travers doit rester récupérable sans repayer.
        state["last_lock_id"] = lock["lock_id"]
    _save_state(state)
    return lock


def last_lock_id() -> str | None:
    return _state().get("last_lock_id")


def lock_status(lock_id: str, timeout: int = 3) -> dict:
    """Timeout court : appelé depuis la boucle d'événements pendant l'attente
    du paiement, un serveur qui pend y figerait le menu."""
    return _request("GET", f"/locks/{lock_id}", timeout=timeout)


def reveal(lock_id: str) -> dict:
    return _request("POST", f"/locks/{lock_id}/reveal")


def checkout(lock_id: str) -> dict:
    return _request("POST", f"/locks/{lock_id}/checkout")
