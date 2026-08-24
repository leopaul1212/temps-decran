"""Empaquetage py2app.

    .venv/bin/python setup.py py2app

Le bundle n'est pas signé : macOS affichera un avertissement Gatekeeper au
premier lancement, et la permission Accessibilité devra être re-accordée à
chaque nouvelle version, l'empreinte du binaire changeant à chaque build.
"""

import os
from pathlib import Path

from setuptools import setup

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
    options={
        "py2app": {
            "argv_emulation": False,
            "iconfile": "assets/icon.icns",
            "plist": {
                "CFBundleName": "Temps d'écran",
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
