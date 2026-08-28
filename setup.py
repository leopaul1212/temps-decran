"""Empaquetage py2app.

    .venv/bin/python setup.py py2app

py2app nomme l'exécutable d'après CFBundleName (« Temps d'écran »). codesign ne
sait pas sceller un bundle dont l'exécutable porte apostrophe et accent : le
bundle sortirait non signé et TCC refuserait alors la permission Accessibilité
(case cochée, process jamais fié, frappe perdue). La commande py2app est donc
étendue ci-dessous pour, après le build, renommer l'exécutable en ASCII puis
sceller le bundle par une signature ad-hoc valide. Tout build — cette commande
lancée à la main comme install.sh — produit ainsi un bundle correct, sans étape
manuelle à reproduire.

Signature : si TEMPS_DECRAN_SIGN_IDENTITY est fourni (empreinte SHA-1 d'un
certificat « Code Signing », cf. ensure-signing-identity.sh), le bundle est signé
avec cette identité — sa Designated Requirement devient stable
(« identifier … and certificate leaf = H"…" »), donc la permission Accessibilité
liée par TCC survit aux reconstructions. À défaut, on retombe sur une signature
ad-hoc (--sign -) : valide mais sans identité stable, l'empreinte (cdhash) change
à chaque build, et l'accès Accessibilité est alors à re-accorder après chaque
mise à jour.
"""

import contextlib
import os
import subprocess
from pathlib import Path

from setuptools import setup

# Nom de fichier ASCII imposé à l'exécutable, à la place du CFBundleName accentué
# que codesign ne sait pas sceller. Le nom affiché reste « Temps d'écran » via
# CFBundleName / CFBundleDisplayName ; seul le fichier exécutable change.
APP_EXECUTABLE = "temps-decran"

# La commande py2app n'est importable qu'une fois py2app installé (setup_requires
# ou pip). Les commandes de métadonnées (egg_info, --help) n'en ont pas besoin :
# on n'échoue donc pas à l'import, on n'étend la commande que si elle est là.
try:
    from py2app.build_app import py2app as _py2app_command
except ImportError:
    _py2app_command = None


def _user_keychains() -> list[str]:
    out = subprocess.check_output(["security", "list-keychains", "-d", "user"], text=True)
    return [line.strip().strip('"') for line in out.splitlines() if line.strip()]


@contextlib.contextmanager
def _keychain_in_search_list(keychain: str):
    """Ajoute temporairement le trousseau à la liste de recherche utilisateur.

    codesign ne trouve une identité que via cette liste (le seul --keychain ne
    suffit pas). On restaure l'état d'origine même si la signature échoue, pour ne
    pas laisser le trousseau de la machine pollué.
    """
    original = _user_keychains()
    if not keychain or keychain in original:
        yield
        return
    subprocess.check_call(["security", "list-keychains", "-d", "user",
                           "-s", keychain, *original])
    try:
        yield
    finally:
        subprocess.check_call(["security", "list-keychains", "-d", "user", "-s", *original])


def _normalize_and_sign(app_path: Path) -> None:
    plist = app_path / "Contents" / "Info.plist"
    macos = app_path / "Contents" / "MacOS"
    current = subprocess.check_output(
        ["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleExecutable", str(plist)],
        text=True,
    ).strip()
    if current != APP_EXECUTABLE:
        (macos / current).rename(macos / APP_EXECUTABLE)
        subprocess.check_call(
            ["/usr/libexec/PlistBuddy",
             "-c", f"Set :CFBundleExecutable {APP_EXECUTABLE}", str(plist)]
        )

    identity = os.environ.get("TEMPS_DECRAN_SIGN_IDENTITY", "").strip()
    keychain = os.environ.get("TEMPS_DECRAN_SIGN_KEYCHAIN", "").strip()
    # --deep : l'exécutable secondaire python et les dylibs embarqués doivent
    # être signés avant le sceau du bundle.
    sign = ["codesign", "--force", "--deep"]
    if identity:
        # Identité stable (certificat auto-signé) → Designated Requirement stable
        # → la permission Accessibilité (TCC) survit aux reconstructions.
        sign += ["--sign", identity]
        if keychain:
            sign += ["--keychain", keychain]
        with _keychain_in_search_list(keychain):
            subprocess.check_call([*sign, str(app_path)])
    else:
        # Ad-hoc : valide mais sans identité stable (cdhash mouvant).
        subprocess.check_call([*sign, "--sign", "-", str(app_path)])
    subprocess.check_call(["codesign", "--verify", str(app_path)])


if _py2app_command is not None:
    class py2app(_py2app_command):
        """py2app + normalisation ASCII et signature ad-hoc valide du bundle."""

        def run(self):
            super().run()
            for app in Path(self.dist_dir).glob("*.app"):
                _normalize_and_sign(app)

    cmdclass = {"py2app": py2app}
else:
    cmdclass = {}


# Gravé dans le bundle pour que le .app téléchargé connaisse son serveur sans
# que l'utilisateur édite state.json. On échoue plutôt que de graver un défaut :
# un build sans serveur (ou pointé sur localhost) produit une app qui meurt
# « serveur injoignable » chez chaque acheteur, silencieusement. On n'accepte
# pas PUBLIC_URL, qui vaut souvent 127.0.0.1 dans le shell de dev.
server = (os.environ.get("TEMPS_DECRAN_SERVER") or "").strip()
if not server:
    raise SystemExit("TEMPS_DECRAN_SERVER manquant : le bundle ne saurait quel serveur interroger.")
if "localhost" in server or "127.0.0.1" in server:
    raise SystemExit(f"TEMPS_DECRAN_SERVER={server} : un bundle distribué ne peut pas pointer sur la machine locale.")
Path("server.txt").write_text(server + "\n")

setup(
    app=["app.py"],
    data_files=["typer.py", "client.py", "server.txt", ("assets", ["assets/temps-decran-logo.png"])],
    cmdclass=cmdclass,
    options={
        "py2app": {
            "argv_emulation": False,
            "iconfile": "assets/icon.icns",
            "plist": {
                "CFBundleName": "Temps d'écran",
                "CFBundleDisplayName": "Temps d'écran",
                "CFBundleIdentifier": "com.leopaul.temps-decran",
                "CFBundleShortVersionString": "0.1.0",
                "NSHumanReadableCopyright": "MIT",
                # Sans ça l'app démarre sans Dock ni fenêtre au premier plan.
                "LSUIElement": False,
            },
            "excludes": ["tkinter", "_tkinter", "numpy", "PIL"],
        }
    },
    setup_requires=["py2app"],
)
