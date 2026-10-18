from __future__ import annotations

import time
from typing import TYPE_CHECKING, Union

import numpy as np
from PIL import Image
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.color import Color
from textual.events import MouseScrollDown, MouseScrollUp, Resize
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import DataTable
from textual.widgets.data_table import ColumnKey

from .api import SearchItem
from .cover import fit_square, render_halfblocks
from .lyrics import Lyrics
from .models import Track
from .themes import VIS_GRADIENTS

if TYPE_CHECKING:
    from .audio import AudioEngine


def theme_color(widget: Widget, name: str, fallback: str = "#888888") -> Color:
    value = widget.app.theme_variables.get(name) or fallback
    try:
        return Color.parse(value)
    except Exception:
        return Color.parse(fallback)


def gradient(start: Color, end: Color, steps: int) -> list[str]:
    if steps <= 1:
        return [start.hex]
    return [start.blend(end, i / (steps - 1)).hex for i in range(steps)]


# ── Visualizador ──────────────────────────────────────────────────────────────
EIGHTHS = " ▁▂▃▄▅▆▇█"
BRAILLE_BITS = np.array([[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]], dtype=np.uint8)


class Visualizer(Widget):
    """Espectro FFT real del audio que está sonando."""

    MODES = ("bars", "mirror", "wave", "off")

    DEFAULT_CSS = """
    Visualizer { height: 9; padding: 0 1; }
    """

    def __init__(
        self, engine: AudioEngine, mode: str = "bars", bar_width: int = 2, gap: int = 1, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.engine = engine
        self.mode = mode if mode in self.MODES else "bars"
        self.bar_width, self.gap = bar_width, gap
        self._levels = np.zeros(0, dtype=np.float32)
        self._peaks = np.zeros(0, dtype=np.float32)
        self._strips: list[Strip] = []
        self._palette: list[str] = []
        self._peak_color = "#ffffff"

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self._update_palette())
        self._update_palette()
        self.set_interval(1 / 30, self._tick)

    def on_resize(self, _event: Resize) -> None:
        self._update_palette()

    def _update_palette(self) -> None:
        height = max(self.content_size.height, 1)
        fixed = VIS_GRADIENTS.get(self.app.theme)
        if fixed:  # paleta clásica del skin (p. ej. el verde→rojo de Winamp)
            self._palette = [fixed[int(i / max(height - 1, 1) * (len(fixed) - 1))] for i in range(height)]
            self._peak_color = "#969696"
            return
        primary = theme_color(self, "primary")
        accent = theme_color(self, "accent", theme_color(self, "secondary").hex)
        self._palette = gradient(primary, accent, height)  # de abajo hacia arriba
        self._peak_color = theme_color(self, "foreground", "#ffffff").hex

    def _tick(self) -> None:
        if self.mode == "off" or not self.display:
            return
        width, height = self.content_size
        if width <= 0 or height <= 0:
            return
        if self.mode == "wave":
            self._strips = self._render_wave(width, height)
        else:
            step = self.bar_width + self.gap
            bands = max((width + self.gap) // step, 1) if self.mode == "bars" else max(width // 2, 1)
            raw = self.engine.spectrum(bands)
            if len(self._levels) != bands:
                self._levels = np.zeros(bands, dtype=np.float32)
                self._peaks = np.zeros(bands, dtype=np.float32)
            rising = raw > self._levels
            self._levels = np.where(rising, self._levels + (raw - self._levels) * 0.65,
                                    self._levels * 0.82 + raw * 0.18)
            self._peaks = np.maximum(self._peaks - 0.012, self._levels)
            if self.mode == "bars":
                self._strips = self._render_bars(width, height)
            else:
                self._strips = self._render_mirror(width, height)
        self.refresh()

    @staticmethod
    def _runs(cells: list[tuple[str, str]], width: int) -> Strip:
        """Agrupa celdas consecutivas con el mismo color en un solo Segment."""
        segments: list[Segment] = []
        run_chars: list[str] = []
        run_color: str | None = None
        for ch, color in cells:
            if color != run_color and run_chars:
                segments.append(Segment("".join(run_chars), Style(color=run_color)))
                run_chars = []
            run_color = color
            run_chars.append(ch)
        if run_chars:
            segments.append(Segment("".join(run_chars), Style(color=run_color)))
        return Strip(segments, width).adjust_cell_length(width)

    def _render_bars(self, width: int, height: int) -> list[Strip]:
        total = height * 8
        fills = (self._levels * total).astype(int)
        peak_rows = np.minimum((self._peaks * height).astype(int), height - 1)
        bw, gap = self.bar_width, self.gap
        offset = (width - (len(fills) * (bw + gap) - gap)) // 2
        strips = []
        for row in range(height):
            from_bottom = height - 1 - row
            color = self._palette[from_bottom]
            cells: list[tuple[str, str]] = [(" ", color)] * max(offset, 0)
            for i, fill in enumerate(fills):
                level = int(min(max(fill - from_bottom * 8, 0), 8))
                if level == 0 and peak_rows[i] == from_bottom and self._peaks[i] > 0.04:
                    cells += [("▁", self._peak_color)] * bw
                else:
                    cells += [(EIGHTHS[level], color)] * bw
                cells += [(" ", color)] * gap
            strips.append(self._runs(cells, width))
        return strips

    def _render_mirror(self, width: int, height: int) -> list[Strip]:
        top_h = (height + 1) // 2
        bottom_h = height - top_h
        fills_top = (self._levels * top_h * 8).astype(int)
        fills_bottom = (self._levels * bottom_h * 2).astype(int)
        offset = (width - len(fills_top) * 2 + 1) // 2
        strips = []
        for row in range(height):
            cells: list[tuple[str, str]] = []
            if row < top_h:
                from_center = top_h - 1 - row
                color = self._palette[min(int(from_center / max(top_h, 1) * height), height - 1)]
                cells = [(" ", color)] * max(offset, 0)
                for fill in fills_top:
                    level = int(min(max(fill - from_center * 8, 0), 8))
                    cells += [(EIGHTHS[level], color), (" ", color)]
            else:
                from_center = row - top_h
                color = self._palette[min(int(from_center / max(bottom_h, 1) * height), height - 1)]
                dim = Color.parse(color).darken(0.35).hex
                cells = [(" ", dim)] * max(offset, 0)
                for fill in fills_bottom:
                    level = int(min(max(fill - from_center * 2, 0), 2))
                    cells += [(" ▀█"[level], dim), (" ", dim)]
            strips.append(self._runs(cells, width))
        return strips

    def _render_wave(self, width: int, height: int) -> list[Strip]:
        dots_x, dots_y = width * 2, height * 4
        samples = self.engine.waveform(1024)
        xs = np.linspace(0, len(samples) - 1, dots_x)
        wave = np.interp(xs, np.arange(len(samples)), samples)
        ys = np.clip(((1 - np.clip(wave * 1.6, -1, 1)) / 2) * (dots_y - 1), 0, dots_y - 1).astype(int)
        grid = np.zeros((dots_y, dots_x), dtype=bool)
        prev = ys[0]
        for x, y in enumerate(ys):
            lo, hi = sorted((prev, y))
            grid[lo:hi + 1, x] = True
            prev = y
        cells = grid.reshape(height, 4, width, 2)
        codes = (cells * BRAILLE_BITS[None, :, None, :]).sum(axis=(1, 3)).astype(int)
        strips = []
        for row in range(height):
            dist = abs(row - (height - 1) / 2) / max((height - 1) / 2, 1)
            color = self._palette[min(int(dist * (height - 1)), height - 1)]
            text = "".join(chr(0x2800 + c) for c in codes[row])
            strips.append(Strip([Segment(text, Style(color=color))], width))
        return strips

    def render_line(self, y: int) -> Strip:
        base = Style(bgcolor=self.rich_style.bgcolor)
        if y < len(self._strips):
            return self._strips[y].apply_style(base)
        return Strip.blank(self.content_size.width, base)


# ── Portada ───────────────────────────────────────────────────────────────────
def placeholder_cover(widget: Widget) -> Image.Image:
    """Degradado con los colores del theme y un vinilo estilizado."""
    a = theme_color(widget, "primary").rgb
    b = theme_color(widget, "accent", theme_color(widget, "secondary").hex).rgb
    bg = theme_color(widget, "surface", "#202020").rgb
    size = 64
    xs, ys = np.meshgrid(np.linspace(0, 1, size), np.linspace(0, 1, size))
    t = ((xs + ys) / 2)[..., None]
    grad = np.array(a) * (1 - t) + np.array(b) * t
    r = np.hypot(xs - 0.5, ys - 0.5)[..., None]
    disc = (r < 0.36) & (r > 0.06)
    img = np.where(disc, np.array(bg) * 0.9 + grad * 0.1, grad)
    img = np.where((r < 0.13) & (r > 0.06), grad, img)
    return Image.fromarray(img.astype(np.uint8), "RGB")


class HiResCover(Widget):
    """Portada a resolución completa vía Sixel / Kitty graphics (textual-image)."""

    DEFAULT_CSS = """
    HiResCover { height: 18; align: center middle; }
    """

    def __init__(self, image_widget: type, aspect: float = 2.0, **kwargs) -> None:
        super().__init__(**kwargs)
        self._image_widget = image_widget
        self.aspect = aspect  # alto/ancho de una celda en píxeles
        self.image: Image.Image | None = None

    def compose(self):
        yield self._image_widget(None)

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self._apply())
        self._apply()

    def on_resize(self, _event: Resize) -> None:
        cols, rows = fit_square(*self.content_size, self.aspect)
        child = self.children[0]
        child.styles.width = cols
        child.styles.height = rows

    def set_image(self, image: Image.Image | None) -> None:
        self.image = image
        self._apply()

    def _apply(self) -> None:
        if self.children:
            self.children[0].image = self.image or placeholder_cover(self)


class CoverArt(Widget):
    DEFAULT_CSS = """
    CoverArt { height: 18; }
    """

    def __init__(self, aspect: float = 2.0, **kwargs) -> None:
        super().__init__(**kwargs)
        self.aspect = aspect
        self.image: Image.Image | None = None
        self._strips: list[Strip] = []
        self._offset_x = 0
        self._offset_y = 0

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self._rebuild())

    def set_image(self, image: Image.Image | None) -> None:
        self.image = image
        self._rebuild()

    def on_resize(self, _event: Resize) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        width, height = self.content_size
        # render_halfblocks escala a cols × 2·rows: con celdas que no son 1:2 eso
        # deforma cada píxel justo lo necesario para que la portada se vea cuadrada.
        cols, rows = fit_square(width, height, self.aspect)
        self._offset_x = (width - cols) // 2
        self._offset_y = (height - rows) // 2
        self._strips = render_halfblocks(self.image or placeholder_cover(self), cols, rows)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        width = self.content_size.width
        row = y - self._offset_y
        if 0 <= row < len(self._strips):
            strip = self._strips[row]
            base = Style(bgcolor=self.rich_style.bgcolor)
            pad = Strip.blank(self._offset_x, base)
            return Strip.join([pad, strip]).adjust_cell_length(width, base)
        return Strip.blank(width, Style(bgcolor=self.rich_style.bgcolor))


# ── Letras ────────────────────────────────────────────────────────────────────
class LyricsView(Widget, can_focus=True):
    DEFAULT_CSS = """
    LyricsView { padding: 1 2; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.lyrics: Lyrics | None = None
        self.status = "Sin reproducción"
        self._active = -1
        self._progress = 0.0
        self._manual_offset = 0
        self._manual_until = 0.0

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self.refresh())

    def set_lyrics(self, lyrics: Lyrics | None, status: str = "") -> None:
        self.lyrics = lyrics
        self.status = status
        self._active = -1
        self._manual_offset = 0
        self.refresh()

    def update_position(self, position: float, duration: float) -> None:
        if not self.lyrics:
            return
        if self.lyrics.synced:
            active = self.lyrics.index_at(position)
            if active != self._active:
                self._active = active
                self.refresh()
        elif duration:
            progress = min(position / duration, 1.0)
            if abs(progress - self._progress) > 0.002:
                self._progress = progress
                self.refresh()
        if self._manual_offset and time.monotonic() > self._manual_until and self.lyrics.synced:
            self._manual_offset = 0
            self.refresh()

    def _scroll(self, delta: int) -> None:
        self._manual_offset += delta
        self._manual_until = time.monotonic() + 4
        self.refresh()

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        self._scroll(2)
        event.stop()

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        self._scroll(-2)
        event.stop()

    def key_down(self) -> None:
        self._scroll(1)

    def key_up(self) -> None:
        self._scroll(-1)

    def render(self) -> Text:
        width, height = self.content_size
        primary = theme_color(self, "primary").hex
        muted = theme_color(self, "foreground", "#cccccc").darken(0.35).hex
        if not self.lyrics or not self.lyrics.lines:
            out = Text("\n" * max(height // 2 - 1, 0), justify="center")
            out.append(self.status or "Sin letra disponible", style=f"italic {muted}")
            return out

        console = self.app.console
        rendered: list[Text] = []
        anchor = 0
        synced = self.lyrics.synced
        for i, line in enumerate(self.lyrics.lines):
            if synced and i == self._active:
                style, anchor = f"bold {primary}", len(rendered)
            elif synced and i < self._active:
                style = muted
            else:
                style = "" if not synced else theme_color(self, "foreground").hex
            text = Text(line or "♪", style=style, justify="center")
            rendered.extend(text.wrap(console, max(width, 1)))
            if synced and i == self._active:
                anchor = (anchor + len(rendered) - 1) // 2

        if synced:
            top = anchor - height // 2 + self._manual_offset
        else:
            top = int(self._progress * max(len(rendered) - height // 2, 0)) - height // 3
            top += self._manual_offset
        top = max(min(top, len(rendered) - 1), -(height // 2))
        window = rendered[max(top, 0): top + height]
        lead = [Text("")] * max(-top, 0)
        footer = Text(f"— {self.lyrics.source} —", style=f"italic {muted}", justify="center")
        lines = lead + window
        if len(lines) < height and top + height >= len(rendered):
            lines.append(Text(""))
            lines.append(footer)
        return Text("\n").join(lines[:height])


# ── Tablas de canciones ───────────────────────────────────────────────────────
Row = Union[Track, SearchItem]


class TrackTable(DataTable):
    """Lista de canciones. `compact` = estilo playlist editor de Winamp (una sola columna)."""

    DEFAULT_CSS = """
    TrackTable { background: $lcd-bg; color: $pl-normal; scrollbar-color: $face-light; }
    TrackTable > .datatable--header { background: $lcd-bg; color: $lcd-fg; text-style: bold; }
    TrackTable > .datatable--cursor { background: $pl-select-bg; color: $pl-normal; text-style: none; }
    TrackTable > .datatable--hover { background: $pl-select-bg 40%; }
    TrackTable:focus > .datatable--cursor { background: $pl-select-bg; text-style: bold; }
    """

    BINDINGS = [
        Binding("left", "app.seek(-5)", "−5s", show=False),
        Binding("right", "app.seek(5)", "+5s", show=False),
    ]

    def __init__(self, role: str, compact: bool = False, **kwargs) -> None:
        super().__init__(cursor_type="row", zebra_stripes=False, show_header=not compact, **kwargs)
        self.role = role
        self.compact = compact
        self.items: list[Row] = []
        self.is_collection = False
        self._current = -1

    def on_mount(self) -> None:
        if self.compact:
            self.add_column("", key="title")
        else:
            self.add_column("", key="mark", width=2)
            self.add_column("Título", key="title")
            self.add_column("Artista", key="artist")
            self.add_column("Álbum", key="album")
        self.add_column("", key="dur", width=7)
        self._fit_columns()
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self.set_items(self.items, self._current))

    def on_resize(self, _event: Resize) -> None:
        self._fit_columns()

    def _fit_columns(self) -> None:
        """Reparte el ancho: sin esto DataTable da a 'Título' todo el espacio."""
        if not self.columns:
            return
        pad = self.cell_padding * 2
        if self.compact:
            widths = {"title": max(self.size.width - 7 - pad * 2 - 2, 10)}
        else:
            # mark (2) + duración (7) + padding de las 5 columnas + scrollbar
            free = max(self.size.width - 9 - pad * 5 - 2, 12)
            if free < 60:  # tabla estrecha: el álbum es lo primero que sobra
                widths = {"title": int(free * 0.6), "album": 0}
                widths["artist"] = free - widths["title"]
            else:
                widths = {"title": int(free * 0.45), "artist": int(free * 0.3)}
                widths["album"] = free - widths["title"] - widths["artist"]
        for key, width in widths.items():
            column = self.columns.get(ColumnKey(key))
            if column:
                column.auto_width = False
                column.width = width
        self._require_update_dimensions = True
        self.refresh()

    def set_items(self, items: list[Row], current: int = -1) -> None:
        cursor = self.cursor_row
        self.items = list(items)
        self._current = current
        self.clear()
        current_style = "bold " + (self.app.theme_variables.get("pl-current") or "white")
        for i, item in enumerate(self.items):
            style = current_style if i == current else ""
            if isinstance(item, SearchItem) and item.kind != "song":
                kind = {"album": "Álbum", "artist": "Artista"}.get(item.kind, "Playlist")
                self.add_row(" ", item.title, item.subtitle, Text(kind, style="italic"), "", key=str(i))
                continue
            track = item.track if isinstance(item, SearchItem) else item
            assert track is not None
            length = Text(track.length, style=style, justify="right")
            if self.compact:
                line = Text(f"{i + 1}. {track.artist} - {track.title}", style=style, no_wrap=True)
                self.add_row(line, length, key=str(i))
            else:
                mark = Text("▶", style=style) if i == current else Text(" ")
                self.add_row(mark, Text(track.title, style=style), Text(track.artist, style=style),
                             Text(track.album, style=style), length, key=str(i))
        if self.items:
            self.move_cursor(row=min(max(cursor, 0), len(self.items) - 1), animate=False)

    def selected(self) -> Row | None:
        if 0 <= self.cursor_row < len(self.items):
            return self.items[self.cursor_row]
        return None

    def selected_track(self) -> Track | None:
        item = self.selected()
        if isinstance(item, SearchItem):
            return item.track
        return item
