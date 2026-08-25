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

Signature ad-hoc : pas de Team ID, donc l'empreinte change à chaque build et la
permission Accessibilité est à re-accorder après chaque mise à jour. Une vraie
identité de signature (même auto-signée) lèverait cette contrainte.
"""

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
    # --deep : l'exécutable secondaire python et les dylibs embarqués doivent
    # être signés avant le sceau du bundle. --sign - : ad-hoc, sans identité.
    subprocess.check_call(["codesign", "--force", "--deep", "--sign", "-", str(app_path)])
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
