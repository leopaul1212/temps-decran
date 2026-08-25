# Temps d'écran

Verrou temporel pour le code Temps d'écran de macOS. Le code est généré par le
serveur, tapé une fois dans le champ système, puis oublié par la machine. Le
récupérer avant l'échéance coûte le prix que tu t'es fixé en le posant, de
1 à 300 €.

Le client ne détient rien : ni le code, ni de quoi le recalculer. Avancer
l'horloge de la machine ne change rien, c'est le serveur qui arbitre.

Ce dépôt contient **le client macOS**. Le service tourne sur
[screentime.mahwai.app](https://screentime.mahwai.app).

## Installer

Une commande : elle clone, compile l'app sur ta machine et l'ouvre.

```
curl -fsSL https://raw.githubusercontent.com/leopaul1212/temps-decran/main/install.sh | bash
```

Compilée localement, l'app n'a pas d'attribut de quarantaine : **aucun
avertissement Gatekeeper** à franchir, contrairement à un `.app` téléchargé.

Deux choses à savoir :

- Il faut un **Python framework de python.org** (3.11+). py2app échoue sur les
  Python de `uv` et de Homebrew, qui lient zlib en statique, et le `python3` de
  macOS (3.9) est trop vieux. La commande te le dira si besoin :
  [python.org/downloads/macos](https://www.python.org/downloads/macos/).
- macOS demandera la permission **Accessibilité** au premier essai de frappe —
  elle sert à taper le code dans le champ système. Réglages Système →
  Confidentialité et sécurité → Accessibilité. Elle est liée à l'empreinte du
  binaire : à ré-accorder après chaque reconstruction.

Pour viser un autre serveur que celui par défaut :

```
curl -fsSL https://raw.githubusercontent.com/leopaul1212/temps-decran/main/install.sh \
  | TEMPS_DECRAN_SERVER=https://mon-serveur bash
```

## Comment ça marche

1. **Tu poses un verrou.** Tu choisis une durée — et ce que craquer avant te
   coûtera, de 1 à 300 €. Le serveur tire un code, l'app le tape dans le champ
   système, puis l'oublie. Le prix se décide là, à froid : le choisir au moment
   où l'on veut déjà le code, ce serait choisir combien on accepte de se punir
   en pleine envie de céder.
2. **Le décompte court.** Tant qu'il tourne, le code reste au serveur. La
   machine ne peut ni le lire ni le recalculer.
3. **L'échéance arrive.** Le code se révèle tout seul, gratuitement. Pressé ?
   Le prix que tu t'étais fixé le libère avant l'heure.

## Développer

```
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
TEMPS_DECRAN_SERVER=https://screentime.mahwai.app .venv/bin/python app.py
```

`snapshot.py` rend les neuf états de la fenêtre en PNG dans `shots/`, sans écran
ni serveur — pratique pour vérifier une retouche d'interface :

```
.venv/bin/python snapshot.py
```

| Fichier | Rôle |
|---|---|
| `app.py` | Fenêtre AppKit + item de barre de menu, machine à états |
| `client.py` | Couche HTTP, token d'appareil dans le trousseau, résolution du serveur |
| `typer.py` | Frappe le code en Unicode (insensible à AZERTY et à Verr. Maj) |
| `snapshot.py` | Rendu hors écran des états de la fenêtre |
| `setup.py` | Empaquetage py2app |

## Empaqueter l'app (bundle .app)

Le bundle demande un **framework build** de python.org — c'est ce que fait
`install.sh`. À la main :

```
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m venv .venv-build
.venv-build/bin/pip install -r requirements.txt py2app
TEMPS_DECRAN_SERVER=https://screentime.mahwai.app .venv-build/bin/python setup.py py2app
```

Le serveur cible est **gravé au build** : `setup.py` échoue plutôt que de livrer
une app qui mourrait « serveur injoignable » au premier lancement. Le résultat
est `dist/Temps d'écran.app`.

`setup.py` étend la commande py2app pour, après le build, **renommer
l'exécutable en `temps-decran` (ASCII)** puis **sceller le bundle par une
signature ad-hoc valide** : codesign ne sait pas signer un exécutable dont le
nom porte apostrophe et accent, et sans sceau valide macOS refuse la permission
Accessibilité (case cochée mais jamais effective). Le nom affiché reste « Temps
d'écran » via `CFBundleName` / `CFBundleDisplayName`. Aucune étape manuelle à
ajouter : tout build passe par là.

La signature reste **ad-hoc et non notarisée** — un `.app` distribué (plutôt que
compilé sur place) déclenche donc Gatekeeper au premier lancement : Réglages
Système → Confidentialité et sécurité → « Ouvrir quand même ». Étant ad-hoc,
l'empreinte change à chaque build : la permission Accessibilité est à
re-accorder après chaque mise à jour. Un compte Apple Developer (99 €/an) avec
signature stable et notarisation ferait disparaître ces deux frictions.

Pour repointer un `.app` déjà installé sans le recompiler :

```
~/Library/Application Support/TempsDEcran/state.json
{"server": "https://mon-serveur"}
```

## Licence

MIT.
