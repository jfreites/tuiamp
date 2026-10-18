"""Piezas del look Winamp 2.x: barra de título, display LCD, marquee y sliders."""

from __future__ import annotations

import time

from rich.text import Text
from textual.color import Color
from textual.events import Click, MouseDown, MouseMove, MouseUp
from textual.message import Message
from textual.widget import Widget

from .models import format_time


def var(widget: Widget, name: str, fallback: str = "#888888") -> str:
    return widget.app.theme_variables.get(name) or fallback


# ── Barra de título ───────────────────────────────────────────────────────────
class WinTitle(Widget):
    """Barra de título rayada, con los botoncitos de la esquina."""

    DEFAULT_CSS = """
    WinTitle { height: 1; background: $face; }
    """

    def __init__(self, title: str, closable: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.closable = closable

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self.refresh())

    def render(self) -> Text:
        width = self.content_size.width
        stripe = var(self, "title-stripe", "#C6A535")
        face_light = var(self, "face-light", "#55557A")
        label = f" {self.title} "
        buttons = " ▁ ▢ ✕ " if self.closable else " ▁ "
        free = max(width - len(label) - len(buttons) - 2, 0)
        left = free // 2
        text = Text(no_wrap=True)
        text.append("▕", style=face_light)
        text.append("≡" * left, style=stripe)
        text.append(label, style="bold " + var(self, "foreground", "#ffffff"))
        text.append("≡" * (free - left), style=stripe)
        text.append("▏", style=face_light)
        text.append(buttons, style=face_light)
        return text

    def on_click(self, event: Click) -> None:
        if self.closable and event.x >= self.content_size.width - 3:
            self.app.exit()


# ── Display LCD ───────────────────────────────────────────────────────────────
# Fuente de 3×5 píxeles; cada fila de celdas pinta dos píxeles con medios bloques.
FONT = {
    "0": ["111", "101", "101", "101", "111"],
    "1": ["001", "001", "001", "001", "001"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "001", "001", "001"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
    ":": ["0", "1", "0", "1", "0"],
    "-": ["000", "000", "111", "000", "000"],
    " ": ["000", "000", "000", "000", "000"],
}
HALF = {(0, 0): " ", (1, 0): "▀", (0, 1): "▄", (1, 1): "█"}


def big_text(value: str) -> list[str]:
    """Convierte '12:34' en 3 líneas de medios bloques."""
    glyphs = [FONT.get(ch, FONT[" "]) for ch in value]
    rows = []
    for pair in ((0, 1), (2, 3), (4, None)):
        line = []
        for g in glyphs:
            top = g[pair[0]]
            bottom = g[pair[1]] if pair[1] is not None else "0" * len(top)
            line.append("".join(HALF[(int(t), int(b))] for t, b in zip(top, bottom, strict=True)) + " ")
        rows.append("".join(line))
    return rows


class LCDTime(Widget):
    """Reloj grande del display. Clic: alterna transcurrido / restante, como Winamp."""

    DEFAULT_CSS = """
    LCDTime { height: 3; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.position = 0.0
        self.duration = 0.0
        self.state = "stop"  # play | pause | stop | load
        self.remaining = False

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self.refresh())

    def render(self) -> Text:
        fg = var(self, "lcd-fg", "#00E200")
        dim = var(self, "lcd-dim", "#1D4F1D")
        icons = {"play": "▶", "pause": "▌▌", "stop": "■", "load": "◌"}
        if self.state == "stop":
            clock = "  :  "
        else:
            seconds = self.duration - self.position if self.remaining and self.duration else self.position
            m, s = divmod(int(max(seconds, 0)), 60)
            clock = f"{min(m, 99):02d}:{s:02d}"
            if self.remaining and self.duration:
                clock = "-" + clock
        # En pausa, el reloj parpadea igual que en Winamp.
        blink_off = self.state == "pause" and int(time.monotonic() * 2) % 2
        rows = big_text(clock.rjust(6))
        text = Text(no_wrap=True)
        for i, row in enumerate(rows):
            icon = icons[self.state] if i == 0 else ""
            text.append(f" {icon:<3}", style=f"bold {fg}")
            text.append(row, style=dim if blink_off else f"bold {fg}")
            if i < 2:
                text.append("\n")
        return text

    def on_click(self, _event: Click) -> None:
        self.remaining = not self.remaining
        self.refresh()


class Marquee(Widget):
    """Título que se desplaza en el display, con los `***` de separación."""

    DEFAULT_CSS = """
    Marquee { height: 1; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.text = "TUIAMP 0.2 — pulsa / para buscar"
        self._offset = 0

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self.refresh())
        self.set_interval(0.22, self._step)

    def set_text(self, text: str) -> None:
        if text != self.text:
            self.text = text
            self._offset = 0
            self.refresh()

    def _step(self) -> None:
        if len(self.text) > self.content_size.width:
            self._offset += 1
            self.refresh()

    def render(self) -> Text:
        width = self.content_size.width
        style = "bold " + var(self, "lcd-fg", "#00E200")
        if len(self.text) <= width:
            return Text(self.text, style=style, no_wrap=True)
        loop = self.text + "  ***  "
        start = self._offset % len(loop)
        return Text((loop * 2)[start: start + width], style=style, no_wrap=True)


class StreamInfo(Widget):
    """`160 kbps  48 kHz     mono stereo`: lo que está encendido brilla."""

    DEFAULT_CSS = """
    StreamInfo { height: 1; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.kbps = 0
        self.khz = 0
        self.channels = 0

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self.refresh())

    def render(self) -> Text:
        fg = "bold " + var(self, "lcd-fg", "#00E200")
        dim = var(self, "lcd-dim", "#1D4F1D")
        width = self.content_size.width
        text = Text(no_wrap=True)
        text.append(f"{self.kbps:>3}" if self.kbps else "   ", style=fg)
        text.append(" kbps  ", style=dim)
        text.append(f"{self.khz:>2}" if self.khz else "  ", style=fg)
        text.append(" kHz", style=dim)
        tail = Text(no_wrap=True)
        tail.append("mono ", style=fg if self.channels == 1 else dim)
        tail.append("stereo", style=fg if self.channels >= 2 else dim)
        text.pad_right(max(width - text.cell_len - tail.cell_len, 1))
        return text + tail


# ── Sliders ───────────────────────────────────────────────────────────────────
class Slider(Widget):
    """Slider horizontal clicable y arrastrable (volumen, balance o posición)."""

    DEFAULT_CSS = """
    Slider { height: 1; }
    """

    class Changed(Message):
        def __init__(self, slider: Slider, value: float) -> None:
            super().__init__()
            self.slider = slider
            self.value = value

        @property
        def control(self) -> Slider:
            return self.slider

    def __init__(self, kind: str, label: str = "", value: float = 0.0, live: bool = True, **kwargs) -> None:
        super().__init__(**kwargs)
        self.kind = kind  # volume | balance | seek
        self.label = label
        self.value = value
        self.live = live  # False: solo avisa al soltar (para no hacer seek en cada píxel)
        self._dragging = False

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self.refresh())

    @property
    def _groove(self) -> tuple[int, int]:
        start = len(self.label) + (1 if self.label else 0)
        return start, max(self.content_size.width - start, 3)

    def set_value(self, value: float) -> None:
        if not self._dragging and abs(value - self.value) > 1e-4:
            self.value = value
            self.refresh()

    def _value_at(self, x: int) -> float:
        start, width = self._groove
        ratio = min(max((x - start) / max(width - 1, 1), 0.0), 1.0)
        return ratio * 2 - 1 if self.kind == "balance" else ratio

    def _ratio(self) -> float:
        return (self.value + 1) / 2 if self.kind == "balance" else self.value

    def render(self) -> Text:
        start, width = self._groove
        dim = var(self, "face-light", "#55557A")
        dark = var(self, "face-dark", "#16161F")
        thumb_style = f"{var(self, 'btn-fg', '#111')} on {var(self, 'btn-face', '#BDBECB')}"
        text = Text(no_wrap=True)
        if self.label:
            text.append(self.label + " ", style="bold " + var(self, "foreground", "#ddd"))
        pos = round(self._ratio() * (width - 1))
        if self.kind == "volume":
            # Como en Winamp: la barra pasa de verde a rojo a medida que sube.
            fill = Color.parse("#1FB01F").blend(Color.parse("#E02C1C"), self.value).hex
            text.append("█" * pos, style=fill)
            text.append("▐", style=thumb_style)
            text.append("░" * (width - pos - 1), style=f"{dim} on {dark}")
        elif self.kind == "balance":
            center = (width - 1) // 2
            color = Color.parse("#1FB01F").blend(Color.parse("#E02C1C"), abs(self.value)).hex
            for i in range(width):
                if i == pos:
                    text.append("▐", style=thumb_style)
                elif min(pos, center) <= i <= max(pos, center):
                    text.append("█", style=color)
                else:
                    text.append("░", style=f"{dim} on {dark}")
        else:
            primary = var(self, "lcd-fg", "#00E200")
            text.append("━" * pos, style=primary)
            text.append("▐█▌"[: max(min(3, width - pos), 1)], style=var(self, "btn-face", "#BDBECB"))
            text.append("─" * max(width - pos - 3, 0), style=dim)
        return text

    def _update_from(self, x: int, final: bool) -> None:
        self.value = self._value_at(x)
        self.refresh()
        if self.live or final:
            self.post_message(self.Changed(self, self.value))

    def on_mouse_down(self, event: MouseDown) -> None:
        self._dragging = True
        self.capture_mouse()
        self._update_from(event.x, final=False)

    def on_mouse_move(self, event: MouseMove) -> None:
        if self._dragging:
            self._update_from(event.x, final=False)

    def on_mouse_up(self, event: MouseUp) -> None:
        if self._dragging:
            self._dragging = False
            self.release_mouse()
            self._update_from(event.x, final=True)


def total_time(seconds: int) -> str:
    return format_time(seconds) if seconds else "0:00"
