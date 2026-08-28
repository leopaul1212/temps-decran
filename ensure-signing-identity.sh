#!/usr/bin/env bash
# Garantit une identité de signature « Code Signing » auto-signée, locale à cette
# machine. Idempotent : crée le certificat au premier appel, le réutilise ensuite.
#
# Pourquoi : une signature ad-hoc (codesign --sign -) n'a pas d'identité stable,
# son empreinte (cdhash) change à chaque build, et macOS TCC lie la permission
# Accessibilité au cdhash — l'utilisateur devrait donc re-accorder l'accès après
# chaque mise à jour. Signé par un certificat, le bundle obtient une Designated
# Requirement stable (« identifier … and certificate leaf = H"…" ») : tant que le
# certificat ne change pas, la permission survit aux reconstructions.
#
# Le certificat vit dans un trousseau DÉDIÉ à mot de passe fixe, pas le trousseau
# de session : aucune saisie du mot de passe utilisateur, aucun dialogue GUI. Ce
# mot de passe ne protège qu'un certificat auto-signé de notre propre app — pas
# un secret. On signe ensuite par l'empreinte du certificat, ce qui fonctionne
# même sans « approuver » le certificat (l'approbation ne sert qu'à Gatekeeper).
#
# Sortie : une ligne « <empreinte-sha1> <chemin-trousseau> » sur stdout. Tout le
# reste (progression, erreurs) part sur stderr, pour que l'appelant puisse faire
#   read HASH KEYCHAIN < <(ensure-signing-identity.sh)
set -euo pipefail

# Nom ASCII : un CN accentué casse la recherche par « security find-certificate -c ».
CN="Temps-decran Local Signing"
KEYCHAIN="$HOME/Library/Keychains/temps-decran-signing.keychain-db"
KC_PASS="temps-decran"

log() { printf '\033[1;34m›\033[0m %s\n' "$1" >&2; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$1" >&2; exit 1; }

# Empreinte SHA-1 du certificat dans le trousseau, ou vide s'il n'y est pas.
hash_of() {
  security find-certificate -c "$CN" -Z "$KEYCHAIN" 2>/dev/null \
    | awk '/SHA-1 hash/{print $NF}' || true
}

if [ -f "$KEYCHAIN" ]; then
  security unlock-keychain -p "$KC_PASS" "$KEYCHAIN" 2>/dev/null \
    || die "Trousseau de signature présent mais mot de passe inattendu. Supprime « $KEYCHAIN » puis relance."
  existing="$(hash_of)"
  if [ -n "$existing" ]; then
    log "Identité de signature déjà en place."
    # Pas d'expiration d'inactivité : le trousseau reste déverrouillé le temps du
    # build (codesign tourne à la toute fin, plusieurs minutes après ici).
    security set-keychain-settings "$KEYCHAIN"
    printf '%s %s\n' "$existing" "$KEYCHAIN"
    exit 0
  fi
  # Trousseau présent mais sans notre certificat : on l'y ajoute plus bas.
fi

log "Création de l'identité de signature locale (une seule fois sur cette machine)…"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# LibreSSL (openssl du système) ne connaît pas -addext de façon fiable : on passe
# les extensions par fichier de config, ce qui marche partout.
cat > "$tmp/cfg.cnf" <<EOF
[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = $CN
[v3]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
EOF

openssl req -x509 -newkey rsa:2048 -nodes -keyout "$tmp/key.pem" -out "$tmp/cert.pem" \
  -days 3650 -config "$tmp/cfg.cnf" >/dev/null 2>&1 \
  || die "Génération du certificat impossible (openssl)."
openssl pkcs12 -export -inkey "$tmp/key.pem" -in "$tmp/cert.pem" -out "$tmp/id.p12" \
  -passout pass:"$KC_PASS" -name "$CN" >/dev/null 2>&1 \
  || die "Empaquetage PKCS#12 impossible (openssl)."

[ -f "$KEYCHAIN" ] || security create-keychain -p "$KC_PASS" "$KEYCHAIN"
security unlock-keychain -p "$KC_PASS" "$KEYCHAIN"
security set-keychain-settings "$KEYCHAIN"
# -T /usr/bin/codesign : seul codesign accède à la clé.
security import "$tmp/id.p12" -k "$KEYCHAIN" -P "$KC_PASS" -T /usr/bin/codesign >/dev/null
# Autorise codesign à utiliser la clé sans dialogue, via le mot de passe (connu)
# du trousseau — pas celui de la session.
security set-key-partition-list -S apple-tool:,apple: -s -k "$KC_PASS" "$KEYCHAIN" >/dev/null 2>&1

created="$(hash_of)"
[ -n "$created" ] || die "Certificat importé mais introuvable dans le trousseau."
log "Identité créée."
printf '%s %s\n' "$created" "$KEYCHAIN"
