#!/usr/bin/env python3
"""Fenêtre macOS pour les verrous temporels.

AppKit directement, sans rumps : la barre de menu seule obligeait à des alertes
modales qui s'ouvraient derrière les autres fenêtres, et chaque état de l'app
passait par une boîte de dialogue qu'il fallait aller chercher.

Le compte à rebours reste aussi dans la barre de menu : pendant les huit
secondes, la fenêtre est justement au second plan puisqu'on clique dans les
Réglages Système.
"""

import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import objc
from AppKit import (
    NSAlert,
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSBox,
    NSBoxSeparator,
    NSButton,
    NSColor,
    NSFont,
    NSImage,
    NSMakeRect,
    NSMakeSize,
    NSMenu,
    NSMenuItem,
    NSPasteboard,
    NSPasteboardTypeString,
    NSPopUpButton,
    NSSlider,
    NSStatusBar,
    NSTextField,
    NSTextAlignmentCenter,
    NSVariableStatusItemLength,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
    NSWorkspace,
)
from Foundation import NSObject, NSTimer, NSURL
from PyObjCTools import AppHelper

import client
import typer

DURATIONS = [
    ("1 minute (test)", 1),
    ("1 heure", 60),
    ("1 jour", 1440),
    ("3 jours", 4320),
    ("7 jours", 10080),
    ("30 jours", 43200),
]
COUNTDOWN = 8
PAYMENT_TIMEOUT = 600
REFRESH_EVERY = 30
LOGO = Path(__file__).parent / "assets" / "temps-decran-logo.png"
ACCESSIBILITY_PANE = (
    "x-apple.systempreferences:com.apple.preference.security"
    "?Privacy_Accessibility"
)

# Hauteur portée de 330 à 410 pour loger le curseur de prix : HEAD_Y, SUB_TOP,
# SEP_Y et BODY_TOP se déduisent de H alors que ROW1_Y/ROW2_Y se comptent
# depuis le bas, si bien qu'agrandir la fenêtre ouvre une bande entre le bas du
# corps et la première rangée d'actions — sans déplacer quoi que ce soit.
W, H = 460, 410
MARGIN = 24
HEAD_Y = H - 70  # centre vertical du titre, fixe : sizeToFit fait varier sa hauteur, pas sa position
SUB_TOP = H - 120
SEP_Y = SUB_TOP - 45
BODY_TOP = SEP_Y - 15
BODY_H = 60
ROW1_Y = 80  # centre vertical de la ligne sélecteur + action principale
ROW2_Y = 40  # centre vertical de l'action secondaire, en retrait sous la première
# Bande du curseur de prix, entre le bas du corps et ROW1. Les bornes tiennent
# sur la même ligne que le montant plutôt que sous le rail : posées en dessous,
# elles venaient buter contre la rangée de boutons.
AMOUNT_ROW_Y = 142
AMOUNT_SLIDER_Y = 116
AMOUNT_SLIDER_W = 280

AMOUNT_MIN, AMOUNT_MAX, AMOUNT_DEFAULT = 1, 300, 10
# Exposant de l'échelle du curseur. Voir amount_from_slider.
AMOUNT_CURVE = 2.2


def amount_from_slider(t: float) -> int:
    """Position du curseur (0 → 1) vers un prix en euros.

    L'échelle est volontairement non linéaire : 300 € étalés uniformément sur
    280 px mettraient 1,07 € par pixel, et la zone 1–20 € — celle où se
    placeront la plupart des choix — tiendrait sur dix-huit pixels. Avec cette
    courbe, la moitié basse de la course couvre 1–66 €.
    """
    euros = AMOUNT_MIN + (AMOUNT_MAX - AMOUNT_MIN) * t ** AMOUNT_CURVE
    # Au-delà de 50 €, arrondi à 5 € : à cet endroit de la course un pixel
    # vaut plus d'un euro, et personne ne cherche à se fixer 287 €.
    step = 5 if euros > 50 else 1
    return max(AMOUNT_MIN, min(AMOUNT_MAX, int(round(euros / step)) * step))


def slider_from_amount(euros: int) -> float:
    """Réciproque de amount_from_slider, pour poser la position de départ."""
    return ((euros - AMOUNT_MIN) / (AMOUNT_MAX - AMOUNT_MIN)) ** (1 / AMOUNT_CURVE)


def format_remaining(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}j {hours}h"
    if hours:
        return f"{hours}h {minutes}min"
    if minutes:
        return f"{minutes}min"
    return f"{secs}s"


def label(frame, size, *, bold=False, grey=False, color=None) -> NSTextField:
    field = NSTextField.alloc().initWithFrame_(frame)
    field.setEditable_(False)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setAlignment_(NSTextAlignmentCenter)
    field.setFont_(
        NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
    )
    if color is not None:
        field.setTextColor_(color)
    elif grey:
        field.setTextColor_(NSColor.secondaryLabelColor())
    return field


class App(NSObject):
    def init(self):
        self = objc.super(App, self).init()
        self.lock = None
        self.offline = False
        self.mode = "idle"  # idle | countdown | confirm | code | paying
        self.notice = ""
        self.shown_code = None
        self.pending_kind = None  # "lock" ou "test"
        self.remaining_ticks = 0
        self.awaiting_payment = None
        self.payment_ticks = 0
        self.ticks = 0
        return self

    # --- construction ---

    @objc.python_method
    def build(self) -> None:
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("Temps d'écran")
        self.window.center()
        self.window.setDelegate_(self)
        view = self.window.contentView()

        # Frame de départ arbitraire : render() recalcule taille et position
        # de chaque champ à chaque affichage (sizeToFit), donc seule la
        # largeur totale ici sert de point de départ.
        self.head = label(NSMakeRect(0, HEAD_Y, W, 40), 30, bold=True)
        self.sub = label(NSMakeRect(MARGIN, SUB_TOP - 18, W - 2 * MARGIN, 18), 13, grey=True)
        self.body = label(NSMakeRect(MARGIN, BODY_TOP - BODY_H, W - 2 * MARGIN, BODY_H), 15)
        self.body.setSelectable_(True)
        for f in (self.head, self.sub, self.body):
            view.addSubview_(f)

        # Séparateur : structure la fenêtre en deux zones (titre / contenu),
        # via NSBox pour rester correct en thème clair comme sombre.
        self.separator = NSBox.alloc().initWithFrame_(
            NSMakeRect(MARGIN, SEP_Y, W - 2 * MARGIN, 1)
        )
        self.separator.setBoxType_(NSBoxSeparator)
        view.addSubview_(self.separator)

        self.picker = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(0, 0, 170, 26), False
        )
        self.picker.addItemsWithTitles_([d[0] for d in DURATIONS])
        self.picker.selectItemAtIndex_(1)
        self.picker.sizeToFit()  # fixe sa hauteur naturelle une fois pour toutes
        picker_frame = self.picker.frame()
        self.picker.setFrame_(NSMakeRect(0, 0, 170, picker_frame.size.height))
        view.addSubview_(self.picker)

        # Le prix de la rechute, fixé à froid au moment de poser le verrou.
        self.amount_label = label(
            NSMakeRect(MARGIN, AMOUNT_ROW_Y, W - 2 * MARGIN, 20), 15, bold=True
        )
        slider_x = (W - AMOUNT_SLIDER_W) / 2
        self.amount_slider = NSSlider.alloc().initWithFrame_(
            NSMakeRect(slider_x, AMOUNT_SLIDER_Y, AMOUNT_SLIDER_W, 20)
        )
        # Le curseur travaille sur 0 → 1, pas sur des euros : c'est
        # amount_from_slider qui porte l'échelle.
        self.amount_slider.setMinValue_(0.0)
        self.amount_slider.setMaxValue_(1.0)
        self.amount_slider.setDoubleValue_(slider_from_amount(AMOUNT_DEFAULT))
        self.amount_slider.setTarget_(self)
        self.amount_slider.setAction_(b"amountChanged:")
        self.amount_min = label(NSMakeRect(slider_x - 30, AMOUNT_ROW_Y + 2, 60, 15), 11, grey=True)
        self.amount_min.setStringValue_(f"{AMOUNT_MIN} €")
        self.amount_max = label(
            NSMakeRect(slider_x + AMOUNT_SLIDER_W - 30, AMOUNT_ROW_Y + 2, 60, 15), 11, grey=True
        )
        self.amount_max.setStringValue_(f"{AMOUNT_MAX} €")
        self.amount_views = (
            self.amount_label,
            self.amount_slider,
            self.amount_min,
            self.amount_max,
        )
        for w in self.amount_views:
            view.addSubview_(w)

        self.primary = self.make_button(NSMakeRect(0, 0, 100, 30), b"primary:")
        self.primary.setKeyEquivalent_("\r")
        self.secondary = self.make_button(NSMakeRect(0, 0, 100, 30), b"secondary:")
        for b in (self.primary, self.secondary):
            view.addSubview_(b)

        self.status = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self.status_icon = NSImage.alloc().initWithContentsOfFile_(str(LOGO))
        self.status_icon.setSize_(NSMakeSize(18, 18))
        self.status_icon.setTemplate_(False)
        self.status.button().setImage_(self.status_icon)
        menu = NSMenu.alloc().init()
        for title, sel in (
            ("Ouvrir la fenêtre", b"show:"),
            ("Copier mon jeton de récupération…", b"copyToken:"),
            ("Quitter", b"terminate:"),
        ):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, "")
            item.setTarget_(self if sel != b"terminate:" else NSApplication.sharedApplication())
            menu.addItem_(item)
        self.status.setMenu_(menu)

    @objc.python_method
    def make_button(self, frame, selector):
        b = NSButton.alloc().initWithFrame_(frame)
        b.setBezelStyle_(NSBezelStyleRounded)
        b.setTarget_(self)
        b.setAction_(selector)
        return b

    # --- rendu ---

    @objc.python_method
    def render(self) -> None:
        head, sub, body = "", "", self.notice
        picker = amount = primary = secondary = None
        status = "Prêt"

        if self.mode == "countdown":
            ticks = max(self.remaining_ticks, 0)
            # Surtout pas le code : l'afficher huit secondes en gros suffirait
            # à le mémoriser, et l'app ne verrouillerait plus rien.
            head = str(ticks)
            sub = "Place le curseur dans le champ, la frappe démarre."
            secondary = "Annuler"
            status = f"Saisie dans {ticks}s"
        elif self.mode == "confirm":
            head = "Vérifie"
            body = "Le code a-t-il bien été saisi deux fois ?"
            primary, secondary = "Oui", "Non, montre-le-moi"
            status = "Saisie"
        elif self.mode == "code":
            head = self.shown_code
            sub = "Note-le si tu en as besoin — il ne sera plus affiché."
            primary = "Je l'ai noté"
            status = "Code affiché"
        elif self.mode == "paying":
            head = "Paiement"
            sub = "Paiement en cours dans le navigateur."
            body = "Le code s'affichera ici dès que Stripe aura confirmé."
            secondary = "Arrêter d'attendre"
            status = "Paiement…"
        elif self.offline:
            head = "Hors ligne"
            sub = f"Serveur injoignable ({client.server_url()})"
            primary = "Réessayer"
            status = "Hors ligne"
        elif self.lock is None and not typer.has_accessibility():
            # Le verrou s'appuie sur la frappe automatique du code : sans la
            # permission Accessibilité, poser un verrou créerait un code que
            # l'app ne pourrait pas saisir. On bloque en amont plutôt que
            # d'échouer après le compte à rebours, verrou déjà créé. Un verrou
            # déjà actif n'est pas concerné : le révéler affiche le code, sans
            # frappe, donc ce garde-fou ne vaut que pour la création.
            head = "Accessibilité requise"
            sub = "Autorise l'app à saisir le code à ta place."
            body = (
                "Réglages Système → Confidentialité et sécurité → "
                "Accessibilité, active « Temps d'écran », puis relance l'app."
            )
            primary = "Ouvrir les réglages"
            status = "Accessibilité requise"
        elif self.lock is None:
            head = "Aucun verrou"
            sub = "Choisis une durée, et ce que craquer avant te coûtera."
            picker, amount, primary = True, True, "Créer le verrou"
            if client.last_lock_id():
                secondary = "Revoir le dernier code"
        else:
            expired = self.lock["expired"]
            head = "Prêt" if expired else format_remaining(self.lock["remaining_seconds"])
            unlock = datetime.fromisoformat(self.lock["unlock_at"]).astimezone()
            sub = (
                "Le verrou est échu, le code est à toi."
                if expired
                else f"Disponible le {unlock.strftime('%a %d %b à %H:%M')}"
            )
            # .get et non [] : une app mise à jour avant le serveur recevrait
            # un verrou sans « price_cents ». render() tourne dans le timer,
            # une KeyError ici rendrait la fenêtre inutilisable à chaque tick.
            price = self.lock.get("price_cents", AMOUNT_DEFAULT * 100) // 100
            primary = (
                "Récupérer le code" if expired else f"Révéler maintenant — {price} €"
            )
            status = "Prêt" if expired else format_remaining(self.lock["remaining_seconds"])

        self.head.setStringValue_(head or "")
        if self.mode in ("countdown", "code"):
            self.head.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(64, 0.3))
        elif self.mode == "paying":
            self.head.setFont_(NSFont.systemFontOfSize_(48))
        else:
            self.head.setFont_(NSFont.boldSystemFontOfSize_(30))

        # Accent réservé aux deux états qui doivent se reconnaître sans lire
        # le texte : verrou actif en cours, et serveur injoignable.
        if self.offline:
            accent = NSColor.systemRedColor()
        elif self.mode == "idle" and self.lock is not None and not self.lock["expired"]:
            accent = NSColor.controlAccentColor()
        else:
            accent = NSColor.labelColor()
        self.head.setTextColor_(accent)
        self.place_hero(self.head)

        self.sub.setStringValue_(sub)
        self.body.setStringValue_(body)

        self.picker.setHidden_(not picker)
        self.amount_label.setStringValue_(f"Craquer : {self.chosen_amount()} €")
        for w in self.amount_views:
            w.setHidden_(not amount)
        for widget, title in ((self.primary, primary), (self.secondary, secondary)):
            widget.setHidden_(title is None)
            if title is not None:
                widget.setTitle_(title)
                widget.sizeToFit()
        self.place_row((self.picker, self.primary), ROW1_Y)
        self.place_row((self.secondary,), ROW2_Y)

        self.status.button().setTitle_(status)

    @objc.python_method
    def place_hero(self, field) -> None:
        """Centre le titre sur une position verticale fixe : sizeToFit fait
        varier sa hauteur selon la police (30pt vs 64pt) sans jamais le
        rogner ni faire sauter sa ligne de base d'un état à l'autre."""
        field.sizeToFit()
        fr = field.frame()
        field.setFrame_(NSMakeRect((W - fr.size.width) / 2, HEAD_Y - fr.size.height / 2, fr.size.width, fr.size.height))

    @objc.python_method
    def place_row(self, widgets, center_y) -> None:
        """Centre en groupe les widgets visibles d'une ligne d'action : leur
        nombre et leur largeur (liée au libellé) changent selon l'état, donc
        aucune position fixe ne conviendrait à tous."""
        visible = [w for w in widgets if not w.isHidden()]
        if not visible:
            return
        gap = 12
        total = sum(w.frame().size.width for w in visible) + gap * (len(visible) - 1)
        x = (W - total) / 2
        for w in visible:
            fr = w.frame()
            w.setFrameOrigin_((x, center_y - fr.size.height / 2))
            x += fr.size.width + gap

    # --- réseau ---

    @objc.python_method
    def refresh(self) -> None:
        try:
            self.lock = client.current_lock()
            self.offline = False
        except client.ServerUnreachable:
            self.offline = True
        except client.ApiError as e:
            self.offline = True
            self.notice = f"Erreur serveur : {e.detail}"

    # --- actions ---

    def amountChanged_(self, sender) -> None:
        # Purement local : rien ne part au serveur tant que le verrou n'est pas
        # posé. render() relit le curseur et rafraîchit le libellé.
        self.render()

    @objc.python_method
    def chosen_amount(self) -> int:
        return amount_from_slider(self.amount_slider.doubleValue())

    def primary_(self, sender) -> None:
        self.guard(self._primary)

    def secondary_(self, sender) -> None:
        self.guard(self._secondary)

    @objc.python_method
    def guard(self, fn) -> None:
        try:
            fn()
        except Exception as e:
            self.notice = f"{type(e).__name__} : {e}"
        self.render()

    @objc.python_method
    def _primary(self) -> None:
        if self.mode == "confirm":
            self.shown_code = None
            self.mode = "idle"
            self.refresh()
        elif self.mode == "code":
            self.shown_code = None
            self.mode = "idle"
            self.refresh()
        elif self.offline:
            self.notice = ""
            self.refresh()
        elif self.lock is None and not typer.has_accessibility():
            self.request_accessibility()
        elif self.lock is None:
            self.create_lock()
        else:
            self.reveal(self.lock["lock_id"])

    @objc.python_method
    def request_accessibility(self) -> None:
        # L'invite système (une fois par lancement) plus l'ouverture directe du
        # volet, pour l'utilisateur qui l'a déjà fermée. Le rendu re-teste la
        # permission chaque seconde et débloque l'écran dès que le système la
        # voit accordée. Mais ce build est signé ad-hoc : un process déjà lancé
        # ne réévalue pas toujours sa confiance à chaud, d'où la consigne de
        # relancer l'app portée par l'écran « Accessibilité requise ».
        typer.prompt_accessibility()
        url = NSURL.URLWithString_(ACCESSIBILITY_PANE)
        NSWorkspace.sharedWorkspace().openURL_(url)

    @objc.python_method
    def _secondary(self) -> None:
        if self.mode == "countdown":
            self.mode = "code" if self.shown_code else "idle"
            self.pending_kind = None
            self.notice = "Frappe annulée." if not self.shown_code else ""
        elif self.mode == "confirm":
            self.mode = "code"
        elif self.mode == "paying":
            self.awaiting_payment = None
            self.mode = "idle"
            self.refresh()
        else:
            last = client.last_lock_id()
            if last:
                self.reveal(last)

    @objc.python_method
    def create_lock(self) -> None:
        minutes = DURATIONS[self.picker.indexOfSelectedItem()][1]
        try:
            result = client.create_lock(minutes, self.chosen_amount() * 100)
        except client.ServerUnreachable:
            self.offline = True
            return
        except client.ApiError as e:
            self.notice = str(e.detail)
            return

        self.notice = ""
        self.shown_code = result["code"]
        self.start_countdown("lock")

    @objc.python_method
    def reveal(self, lock_id: str) -> None:
        try:
            self.shown_code = client.reveal(lock_id)["code"]
            self.mode = "code"
            self.notice = ""
        except client.ServerUnreachable:
            self.offline = True
        except client.ApiError as e:
            if e.status == 402:
                self.start_payment(lock_id)
            else:
                self.notice = str(e.detail)

    # --- paiement ---

    @objc.python_method
    def start_payment(self, lock_id: str) -> None:
        try:
            url = client.checkout(lock_id)["checkout_url"]
        except client.ServerUnreachable:
            self.offline = True
            return
        except client.ApiError as e:
            self.notice = f"Paiement impossible : {e.detail}"
            return

        webbrowser.open(url)
        self.awaiting_payment = lock_id
        self.payment_ticks = 0
        self.notice = ""
        self.mode = "paying"

    @objc.python_method
    def poll_payment(self) -> None:
        """Le webhook arrive sur le serveur, pas ici : on interroge le verrou
        jusqu'à ce que Stripe l'ait marqué payé."""
        self.payment_ticks += 1
        if self.payment_ticks > PAYMENT_TIMEOUT:
            self.awaiting_payment = None
            self.mode = "idle"
            self.notice = (
                "Paiement non détecté. Si tu as bien payé, "
                "clique à nouveau sur Révéler : ce sera sans repayer."
            )
            self.refresh()
            return
        if self.payment_ticks % 2:
            return
        try:
            if not client.lock_status(self.awaiting_payment)["paid"]:
                return
        except (client.ServerUnreachable, client.ApiError):
            return  # transitoire, on réessaiera

        lock_id, self.awaiting_payment = self.awaiting_payment, None
        self.mode = "idle"
        self.reveal(lock_id)

    # --- compte à rebours ---

    @objc.python_method
    def start_countdown(self, kind: str) -> None:
        self.pending_kind = kind
        self.remaining_ticks = COUNTDOWN
        self.mode = "countdown"
        self.window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def fire_typing(self) -> None:
        kind, self.pending_kind = self.pending_kind, None
        try:
            typer.type_code(self.shown_code if kind == "lock" else "1234")
        except Exception as e:
            self.notice = str(e)
            self.mode = "code" if kind == "lock" else "idle"
            return

        if kind == "lock":
            self.mode = "confirm"
        else:
            self.mode = "idle"
            self.shown_code = None
            self.notice = "Frappe de test terminée."
            self.refresh()

    def tick_(self, timer) -> None:
        self.ticks += 1
        if self.mode == "countdown":
            self.remaining_ticks -= 1
            if self.remaining_ticks <= 0:
                self.guard(self.fire_typing)
                return
        elif self.mode == "paying":
            self.guard(self.poll_payment)
            return
        elif self.mode == "idle" and self.ticks % REFRESH_EVERY == 0:
            self.refresh()
        self.render()

    # --- cycle de vie ---

    def show_(self, sender) -> None:
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)

    def copyToken_(self, sender) -> None:
        # Le jeton identifie l'appareil auprès du serveur ; il ne déverrouille
        # rien. Le noter permet de retrouver et payer son code sur le site même
        # après désinstallation — sans jeton, le verrou devient injoignable.
        token = client.device_token()
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(token, NSPasteboardTypeString)
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Jeton de récupération copié")
        alert.setInformativeText_(
            "Colle-le en lieu sûr, dans tes notes ou un mot de passe, "
            "AVANT de désinstaller l'app.\n\n"
            "Avec ce jeton tu pourras retrouver et débloquer ton code sur "
            "screentime.mahwai.app/recover, même sans l'app installée. "
            "Sans lui, un verrou en cours devient irrécupérable.\n\n"
            + token
        )
        alert.runModal()

    def windowShouldClose_(self, sender) -> bool:
        # La fenêtre se referme, l'app continue : le décompte doit rester
        # visible dans la barre de menu même sans fenêtre à l'écran.
        self.window.orderOut_(None)
        return False

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visible) -> bool:
        self.window.makeKeyAndOrderFront_(None)
        return True

    def applicationDidFinishLaunching_(self, notification) -> None:
        self.build()
        self.refresh()
        self.render()
        self.window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, b"tick:", None, True
        )


def main() -> None:
    app = NSApplication.sharedApplication()
    # Regular et non Accessory : c'est ce qui donne une icône dans le Dock et
    # une fenêtre qui passe au premier plan quand on la demande.
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = App.alloc().init()
    app.setDelegate_(delegate)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
