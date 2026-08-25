"""Empaquetage py2app.

    .venv/bin/python setup.py py2app

py2app produit un exécutable nommé d'après CFBundleName (« Temps d'écran »).
codesign ne sait pas sceller un bundle dont l'exécutable porte apostrophe et
accent : c'est install.sh qui, après le build, renomme l'exécutable en ASCII
et scelle le bundle par une signature ad-hoc valide — sans quoi TCC refuse la
permission Accessibilité (voir le commentaire dédié dans install.sh). Un build
lancé à la main par cette commande doit donc reproduire ces deux étapes.

Signature ad-hoc : pas de Team ID, donc l'empreinte change à chaque build et la
permission Accessibilité est à re-accorder après chaque mise à jour. Une vraie
identité de signature (même auto-signée) lèverait cette contrainte.
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
