"""Portadas: descarga con caché, render con medios bloques y paleta para el theme dinámico."""

from __future__ import annotations

import colorsys
import hashlib
from io import BytesIO

import httpx
from PIL import Image
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip

from .config import CACHE_DIR

COVER_DIR = CACHE_DIR / "covers"


def detect_graphics_widget() -> type | None:
    """Devuelve el widget de textual-image si la terminal soporta Sixel o Kitty (TGP).

    Debe llamarse ANTES de arrancar la app: la detección consulta a la terminal por stdin.
    """
    try:
        from textual_image.renderable import Image as AutoRenderable
        from textual_image.renderable.sixel import Image as SixelRenderable
        from textual_image.renderable.tgp import Image as TGPRenderable
        from textual_image.widget import Image as ImageWidget
    except Exception:
        return None
    if AutoRenderable in (SixelRenderable, TGPRenderable):
        return ImageWidget
    return None


def terminal_cell_aspect() -> float:
    """Alto/ancho de una celda de la terminal en píxeles (2.0 si no se puede saber).

    Sirve para que la portada salga cuadrada: con fuentes altas una celda mide ~1:3.
    Usa la consulta que textual-image ya hizo al detectar los gráficos (está cacheada).
    """
    try:
        from textual_image._terminal import get_cell_size

        size = get_cell_size()
        if size.width > 0 and size.height > 0:
            return min(max(size.height / size.width, 1.5), 3.5)
    except Exception:
        pass
    return 2.0


def fit_square(width: int, height: int, aspect: float) -> tuple[int, int]:
    """Columnas × filas del mayor cuadrado (en píxeles) que cabe en width × height celdas."""
    if width >= height * aspect:
        return max(round(height * aspect), 1), height
    return width, max(round(width / aspect), 1)


def fetch_cover(url: str) -> Image.Image | None:
    if not url:
        return None
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    path = COVER_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".img")
    try:
        if not path.exists():
            resp = httpx.get(url, timeout=10, follow_redirects=True)
            resp.raise_for_status()
            path.write_bytes(resp.content)
        image = Image.open(BytesIO(path.read_bytes()))
        return image.convert("RGB")
    except Exception:
        return None


def render_halfblocks(image: Image.Image, cols: int, rows: int) -> list[Strip]:
    """Cada celda muestra 2 píxeles verticales: '▀' con fg = arriba y bg = abajo."""
    if cols <= 0 or rows <= 0:
        return []
    img = image.resize((cols, rows * 2), Image.Resampling.LANCZOS)
    px = img.load()
    strips: list[Strip] = []
    for y in range(rows):
        segments = []
        for x in range(cols):
            top = px[x, y * 2]
            bottom = px[x, y * 2 + 1]
            style = Style(color=f"rgb({top[0]},{top[1]},{top[2]})",
                          bgcolor=f"rgb({bottom[0]},{bottom[1]},{bottom[2]})")
            segments.append(Segment("▀", style))
        strips.append(Strip(segments, cols))
    return strips


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(c * 255))) for c in rgb))


def cover_palette(image: Image.Image) -> dict[str, str]:
    """Extrae colores dominantes y deriva una paleta legible (fondo oscuro, acentos vivos)."""
    small = image.resize((64, 64))
    quant = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = quant.getpalette() or []
    counts = sorted(quant.getcolors() or [], reverse=True)
    colors = []
    for count, idx in counts:
        r, g, b = (c / 255 for c in palette[idx * 3: idx * 3 + 3])
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        colors.append((count, h, l, s))

    # El acento principal: el color más saturado con presencia razonable.
    vivid = sorted(colors, key=lambda c: c[3] * (0.4 + min(c[0] / 600, 1.0)), reverse=True)
    base_h = colors[0][1] if colors else 0.0
    p_h, _, p_s = (vivid[0][1], 0, vivid[0][3]) if vivid else (base_h, 0, 0.5)
    s_h = vivid[1][1] if len(vivid) > 1 else (p_h + 0.08) % 1
    a_h = vivid[2][1] if len(vivid) > 2 else (p_h + 0.5) % 1
    sat = max(p_s, 0.45)

    def hls(h: float, l: float, s: float) -> str:
        return _hex(colorsys.hls_to_rgb(h, l, s))

    return {
        "primary": hls(p_h, 0.62, sat),
        "secondary": hls(s_h, 0.55, max(sat * 0.8, 0.35)),
        "accent": hls(a_h, 0.66, max(sat, 0.5)),
        "background": hls(base_h, 0.07, min(sat, 0.35)),
        "surface": hls(base_h, 0.11, min(sat, 0.3)),
        "panel": hls(base_h, 0.16, min(sat, 0.3)),
        "foreground": hls(base_h, 0.9, 0.15),
    }
