"""Ventana del ecualizador de Winamp 2.x: preamp + 10 bandas de ±12 dB, ON/AUTO y presets."""

from __future__ import annotations

from rich.text import Text
from textual.color import Color
from textual.events import MouseDown, MouseMove, MouseScrollDown, MouseScrollUp, MouseUp
from textual.message import Message
from textual.widget import Widget

from .audio import EQ_BANDS, EQ_RANGE
from .themes import VIS_GRADIENTS
from .winamp import var

PREAMP = -1  # índice del slider del preamp
BAND_LABELS = ["60", "170", "310", "600", "1K", "3K", "6K", "12K", "14K", "16K"]
assert len(BAND_LABELS) == len(EQ_BANDS)

# Presets de Winamp (winamp.q1), pasados a dB y recortados a ±12. Preamp, luego las 10 bandas.
EQ_PRESETS: dict[str, tuple[float, list[float]]] = {
    "Flat": (0.0, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    "Classical": (0.0, [0, 0, 0, 0, 0, 0, -7.2, -7.2, -7.2, -9.6]),
    "Club": (0.0, [0, 0, 8, 5.6, 5.6, 5.6, 3.2, 0, 0, 0]),
    "Dance": (0.0, [9.6, 7.2, 2.4, 0, 0, -5.6, -7.2, -7.2, 0, 0]),
    "Full Bass": (-4.0, [9.6, 9.6, 9.6, 5.6, 1.6, -4, -8, -10.4, -11.2, -11.2]),
    "Full Bass & Treble": (-4.0, [7.2, 5.6, 0, -7.2, -4.8, 1.6, 8, 11.2, 12, 12]),
    "Full Treble": (-6.0, [-9.6, -9.6, -9.6, -4, 2.4, 11.2, 12, 12, 12, 12]),
    "Headphones": (-3.0, [4.8, 11.2, 5.6, -3.2, -2.4, 1.6, 4.8, 9.6, 12, 12]),
    "Large Hall": (0.0, [10.4, 10.4, 5.6, 5.6, 0, -4.8, -4.8, -4.8, 0, 0]),
    "Live": (0.0, [-4.8, 0, 4, 5.6, 5.6, 5.6, 4, 2.4, 2.4, 2.4]),
    "Party": (0.0, [7.2, 7.2, 0, 0, 0, 0, 0, 0, 7.2, 7.2]),
    "Pop": (0.0, [-1.6, 4.8, 7.2, 8, 5.6, 0, -2.4, -2.4, -1.6, -1.6]),
    "Reggae": (0.0, [0, 0, 0, -5.6, 0, 6.4, 6.4, 0, 0, 0]),
    "Rock": (-2.0, [8, 4.8, -5.6, -8, -3.2, 4, 8.8, 11.2, 11.2, 11.2]),
    "Ska": (0.0, [-2.4, -4.8, -4, 0, 4, 5.6, 8.8, 9.6, 11.2, 9.6]),
    "Soft": (0.0, [4.8, 1.6, 0, -2.4, 0, 4, 8, 9.6, 11.2, 12]),
    "Soft Rock": (0.0, [4, 4, 2.4, 0, -4, -5.6, -3.2, 0, 2.4, 8.8]),
    "Techno": (0.0, [8, 5.6, 0, -5.6, -4.8, 0, 8, 9.6, 9.6, 8.8]),
}


def clamp_db(value: float) -> float:
    return round(min(max(value, -EQ_RANGE), EQ_RANGE), 1)


def level_palette(widget: Widget, steps: int) -> list[str]:
    """Degradado de abajo hacia arriba: el del espectro del skin, o primary → accent."""
    fixed = VIS_GRADIENTS.get(widget.app.theme)
    if fixed:
        return [fixed[round(i / max(steps - 1, 1) * (len(fixed) - 1))] for i in range(steps)]
    start = Color.parse(var(widget, "lcd-fg", "#00E200"))
    try:
        end = Color.parse(widget.app.current_theme.accent or "#EF3110")
    except Exception:
        end = Color.parse("#EF3110")
    return [start.blend(end, i / max(steps - 1, 1)).hex for i in range(steps)]


class EQSlider(Widget):
    """Slider vertical de una banda: clic/arrastre para fijarlo, la rueda afina de 1 en 1 dB."""

    DEFAULT_CSS = """
    EQSlider { width: 3; height: 8; margin-right: 1; }
    """

    class Changed(Message):
        def __init__(self, slider: EQSlider, value: float, final: bool) -> None:
            super().__init__()
            self.slider = slider
            self.value = value
            self.final = final

        @property
        def control(self) -> EQSlider:
            return self.slider

    def __init__(self, band: int, label: str, value: float = 0.0, **kwargs) -> None:
        super().__init__(**kwargs)
        self.band = band  # PREAMP o 0..9
        self.label = label
        self.value = clamp_db(value)
        self._dragging = False

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self.refresh())

    @property
    def _rows(self) -> int:
        return max(self.content_size.height - 1, 3)  # la última fila es la etiqueta

    def set_value(self, value: float) -> None:
        value = clamp_db(value)
        if value != self.value:
            self.value = value
            self.refresh()

    def _thumb_row(self) -> int:
        return round((EQ_RANGE - self.value) / (2 * EQ_RANGE) * (self._rows - 1))

    def render(self) -> Text:
        rows, width = self._rows, max(self.content_size.width, 1)
        bg = var(self, "lcd-bg", "#000000")
        groove = var(self, "face-light", "#55557A")
        thumb_style = f"bold {var(self, 'btn-face', '#BDBECB')} on {bg}"
        palette = level_palette(self, rows)
        center = (rows - 1) // 2
        thumb = self._thumb_row()
        pad = " " * ((width - 1) // 2)
        text = Text(no_wrap=True)
        for r in range(rows):
            level = rows - 1 - r  # 0 = abajo
            if r == thumb:
                text.append("━" * width, style=thumb_style)
            elif min(center, thumb) <= r <= max(center, thumb) and thumb != center:
                text.append(pad + "█" + pad, style=f"{palette[level]} on {bg}")
            elif r == center:
                text.append(pad + "┼" + pad, style=f"{groove} on {bg}")
            else:
                text.append(pad + "│" + pad, style=f"{groove} on {bg}")
            text.append("\n")
        label_style = "bold " + var(self, "lcd-fg" if self._dragging else "foreground", "#dddddd")
        text.append(self.label.center(width)[:width], style=label_style)
        return text

    def _value_at(self, y: int) -> float:
        ratio = min(max(y / max(self._rows - 1, 1), 0.0), 1.0)
        return clamp_db(EQ_RANGE - ratio * 2 * EQ_RANGE)

    def _change(self, value: float, final: bool) -> None:
        self.value = clamp_db(value)
        self.refresh()
        self.post_message(self.Changed(self, self.value, final))

    def on_mouse_down(self, event: MouseDown) -> None:
        if event.y >= self._rows:
            return  # clic en la etiqueta
        self._dragging = True
        self.capture_mouse()
        self._change(self._value_at(event.y), final=False)

    def on_mouse_move(self, event: MouseMove) -> None:
        if self._dragging:
            self._change(self._value_at(event.y), final=False)

    def on_mouse_up(self, event: MouseUp) -> None:
        if self._dragging:
            self._dragging = False
            self.release_mouse()
            self._change(self._value_at(event.y), final=True)

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        event.stop()
        self._change(self.value + 1, final=True)

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        event.stop()
        self._change(self.value - 1, final=True)


class EQScale(Widget):
    """La regla `+12db / +0db / -12db` entre el preamp y las bandas."""

    DEFAULT_CSS = """
    EQScale { width: 4; height: 8; margin-right: 1; }
    """

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self.refresh())

    def render(self) -> Text:
        rows = max(self.content_size.height - 1, 3)
        style = var(self, "lcd-fg", "#00E200")
        marks = {0: "+12", (rows - 1) // 2: " +0", rows - 1: "-12"}
        text = Text(no_wrap=True)
        for r in range(rows):
            text.append(marks.get(r, "").rjust(4), style=style)
            text.append("\n")
        text.append(" dB ", style=var(self, "foreground", "#dddddd"))
        return text
