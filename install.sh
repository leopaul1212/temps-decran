#!/usr/bin/env bash
# Installe Temps d'écran depuis les sources, en une commande :
#
#   curl -fsSL https://raw.githubusercontent.com/leopaul1212/temps-decran/main/install.sh | bash
#
# Compilé localement, le bundle n'a pas d'attribut de quarantaine : aucun
# avertissement Gatekeeper au lancement, contrairement au .app téléchargé.
set -euo pipefail

# À remplacer par le domaine de ton serveur déployé. Surchargeable :
#   ... | TEMPS_DECRAN_SERVER=https://mon-serveur bash
SERVER="${TEMPS_DECRAN_SERVER:-https://screentime.mahwai.app}"
REPO="${TEMPS_DECRAN_REPO:-https://github.com/leopaul1212/temps-decran}"
APP_NAME="Temps d'écran.app"

say() { printf '\033[1;34m›\033[0m %s\n' "$1"; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$1" >&2; exit 1; }

# py2app exige un « framework build » de python.org : les Python de uv/brew
# lient zlib en statique et échouent. /usr/bin/python3 (3.9) est trop vieux.
#
# On essaie d'abord les versions sur lesquelles py2app est éprouvé, puis on
# retombe sur la plus récente installée : quelqu'un qui suit le lien de
# python.org récupère la version du jour, et coder la liste en dur ferait
# échouer l'installation chez lui à chaque nouvelle sortie de Python.
FRAMEWORKS="/Library/Frameworks/Python.framework/Versions"
newer="$(ls "$FRAMEWORKS" 2>/dev/null | grep -E '^3\.[0-9]+$' | sort -t. -k2,2nr)"
PY=""
for v in 3.13 3.12 3.11 $newer; do
  case " 3.13 3.12 3.11 " in *" $v "*) ;; *) [ "${v#3.}" -ge 11 ] || continue ;; esac
  cand="$FRAMEWORKS/$v/bin/python3"
  [ -x "$cand" ] && { PY="$cand"; break; }
done
[ -n "$PY" ] || die "Aucun Python framework (3.11+) trouvé. Installe-le depuis https://www.python.org/downloads/macos/ puis relance."

command -v git >/dev/null || die "git est requis (installe les outils en ligne de commande : xcode-select --install)."

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

say "Clonage des sources…"
git clone --depth 1 "$REPO" "$work/src" >/dev/null 2>&1 || die "Clonage impossible depuis $REPO."
cd "$work/src"

say "Construction de l'app (quelques minutes)…"
log="${TMPDIR:-/tmp}/temps-decran-build.log"
: >"$log"
build() { "$@" >>"$log" 2>&1 || die "Échec de la construction. Journal : $log"; }
build "$PY" -m venv .venv-build
build .venv-build/bin/pip install --quiet --upgrade pip
build .venv-build/bin/pip install --quiet -r requirements.txt py2app
TEMPS_DECRAN_SERVER="$SERVER" build .venv-build/bin/python setup.py py2app

[ -d "dist/$APP_NAME" ] || die "La construction n'a pas produit dist/$APP_NAME (journal : $log)."

dest="$HOME/Applications"
mkdir -p "$dest"
rm -rf "$dest/$APP_NAME"
cp -R "dist/$APP_NAME" "$dest/"

say "Installé dans $dest/$APP_NAME"
say "macOS demandera l'accès Accessibilité au premier essai de frappe : Réglages Système → Confidentialité et sécurité → Accessibilité."
open "$dest/$APP_NAME"
