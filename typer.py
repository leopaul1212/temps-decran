#!/usr/bin/env python3
"""Frappe du code dans le champ système.

Appelé dans le processus de l'app : en bundle py2app, `sys.executable` désigne
l'app elle-même, donc relancer un interpréteur sur ce fichier ne taperait rien.

Reste exécutable seul pour le débogage, le code arrivant alors sur stdin et non
par argv, qui serait lisible via `ps`.

On tape via `CGEventKeyboardSetUnicodeString`, qui injecte le caractère Unicode
tel quel. Passer par des keycodes (ce que fait pyautogui) suppose un clavier US :
sur AZERTY la rangée du haut donne « & é " ' » sans Maj, donc un code chiffré
sortait en caractères aléatoires tant que Maj/Verr. Maj n'était pas activé.
"""

import sys
import time

from ApplicationServices import (
    AXIsProcessTrustedWithOptions,
    CGEventCreateKeyboardEvent,
    CGEventKeyboardSetUnicodeString,
    CGEventPost,
    kAXTrustedCheckOptionPrompt,
    kCGHIDEventTap,
)

SEPARATOR_DELAY = 0.5
TYPE_INTERVAL = 0.1
KEYCODE_TAB = 0x30


def require_accessibility() -> None:
    """Sans cette permission, les événements postés ne vont nulle part : aucune
    frappe, aucune exception, code perdu. On échoue franchement."""
    if AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}):
        return
    raise RuntimeError(
        "Permission Accessibilité refusée.\n"
        "Réglages Système → Confidentialité et sécurité → Accessibilité, "
        "ajoute l'app, puis relance-la."
    )


def _press_key(keycode: int) -> None:
    for down in (True, False):
        CGEventPost(kCGHIDEventTap, CGEventCreateKeyboardEvent(None, keycode, down))


def _type_char(char: str) -> None:
    for down in (True, False):
        event = CGEventCreateKeyboardEvent(None, 0, down)
        CGEventKeyboardSetUnicodeString(event, len(char), char)
        CGEventPost(kCGHIDEventTap, event)


def _typewrite(text: str) -> None:
    for char in text:
        _type_char(char)
        time.sleep(TYPE_INTERVAL)


def type_code(code: str, once: bool = False) -> None:
    require_accessibility()

    time.sleep(0.3)
    _typewrite(code)
    if once:
        return

    _press_key(KEYCODE_TAB)
    time.sleep(SEPARATOR_DELAY)
    _typewrite(code)


if __name__ == "__main__":
    code = sys.stdin.read().strip()
    if not code:
        raise SystemExit("Aucun code reçu sur stdin.")
    type_code(code, once="--once" in sys.argv)
