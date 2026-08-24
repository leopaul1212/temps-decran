#!/usr/bin/env python3
"""Rend la fenêtre dans chacun de ses états, en PNG, sans réseau ni écran.

La vue se dessine elle-même dans un bitmap : pas besoin de la permission
Enregistrement de l'écran, et pas besoin d'un serveur en face. C'est le seul
moyen de vérifier la mise en page autrement qu'à l'œil.
"""

import sys
from pathlib import Path

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBitmapImageFileTypePNG,
    NSColor,
)

import app

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "shots")

FUTURE = "2026-08-30T18:30:00+00:00"
STATES = {
    "idle": dict(lock=None),
    "locked": dict(lock={"lock_id": "abc", "unlock_at": FUTURE, "remaining_seconds": 22530, "expired": False, "paid": False}),
    "ready": dict(lock={"lock_id": "abc", "unlock_at": FUTURE, "remaining_seconds": 0, "expired": True, "paid": False}),
    "countdown": dict(mode="countdown", remaining_ticks=5, shown_code="2115"),
    "confirm": dict(mode="confirm", shown_code="2115"),
    "code": dict(mode="code", shown_code="2115"),
    "paying": dict(mode="paying"),
    "offline": dict(offline=True),
    "erreur": dict(lock=None, notice="Un verrou est déjà actif sur cet appareil."),
}


def main() -> None:
    ns = NSApplication.sharedApplication()
    ns.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    OUT.mkdir(exist_ok=True)

    for name, state in STATES.items():
        ui = app.App.alloc().init()
        ui.build()
        for key, value in state.items():
            setattr(ui, key, value)
        ui.render()

        view = ui.window.contentView()
        # Le fond appartient à la fenêtre, pas à la vue : hors écran il n'est
        # pas peint, et le texte du thème sortirait blanc sur blanc.
        view.setWantsLayer_(True)
        view.layer().setBackgroundColor_(NSColor.windowBackgroundColor().CGColor())
        rect = view.bounds()
        rep = view.bitmapImageRepForCachingDisplayInRect_(rect)
        view.cacheDisplayInRect_toBitmapImageRep_(rect, rep)
        png = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
        path = OUT / f"{name}.png"
        png.writeToFile_atomically_(str(path), True)
        print(f"{path}  {rep.pixelsWide()}x{rep.pixelsHigh()}")


if __name__ == "__main__":
    main()
