from __future__ import annotations

from textual.color import Color
from textual.theme import Theme

COVER_THEME = "cover-art"
WINAMP_THEME = "winamp-classic"

# Colores del skin "Base" de Winamp 2.x: viscolor.txt (espectro) y pledit.txt (playlist).
WINAMP_VARIABLES = {
    "lcd-bg": "#000000",
    "lcd-fg": "#00E200",
    "lcd-dim": "#1D4F1D",
    "pl-normal": "#00FF00",
    "pl-current": "#FFFFFF",
    "pl-select-bg": "#0000C6",
    "face": "#2A2A40",
    "face-light": "#55557A",
    "face-dark": "#16161F",
    "title-stripe": "#C6A535",
    "btn-face": "#BDBECB",
    "btn-fg": "#1A1A24",
}

# Degradado del analizador de espectro de Winamp, de abajo (verde) hacia arriba (rojo).
VIS_GRADIENTS = {
    WINAMP_THEME: [
        "#189408", "#299C08", "#31A510", "#39B510", "#32BE10", "#29CE10", "#94DE21", "#BDDE29",
        "#D6B521", "#DEA518", "#C67B08", "#D67300", "#D66600", "#D65A00", "#CE2921", "#EF3110",
    ],
}


def skin_defaults(theme: Theme) -> dict[str, str]:
    """Variables del look Winamp para cualquier theme: el resto de themes actúan como skins."""
    def c(value: str | None, fallback: str) -> Color:
        try:
            return Color.parse(value or fallback)
        except Exception:
            return Color.parse(fallback)

    primary = c(theme.primary, "#00E200")
    background = c(theme.background, "#101010")
    surface = c(theme.surface, background.hex)
    panel = c(theme.panel, surface.hex)
    foreground = c(theme.foreground, "#DDDDDD")
    secondary = c(theme.secondary, primary.hex)
    lcd = background.darken(0.06) if theme.dark else background.darken(0.85)
    return {
        "lcd-bg": lcd.hex,
        "lcd-fg": primary.hex,
        "lcd-dim": lcd.blend(primary, 0.28).hex,
        "pl-normal": (foreground if theme.dark else Color.parse("#E8E8E8")).hex,
        "pl-current": primary.lighten(0.15).hex,
        "pl-select-bg": lcd.blend(primary, 0.32).hex,
        "face": surface.hex,
        "face-light": panel.lighten(0.08).hex,
        "face-dark": background.darken(0.1).hex,
        "title-stripe": secondary.hex,
        "btn-face": panel.lighten(0.25).hex,
        "btn-fg": foreground.hex if panel.lighten(0.25).brightness < 0.5 else "#111111",
    }

CUSTOM_THEMES = [
    Theme(
        name=WINAMP_THEME,
        primary="#00E200",
        secondary="#C6A535",
        accent="#EF3110",
        foreground="#DCDCE8",
        background="#1C1C2A",
        surface="#2A2A40",
        panel="#3C3C58",
        success="#00E200",
        warning="#D6B521",
        error="#EF3110",
        dark=True,
        variables=WINAMP_VARIABLES,
    ),
    Theme(
        name="youtube-music",
        primary="#FF0033",
        secondary="#FF5C7A",
        accent="#FFB4C2",
        foreground="#F1F1F1",
        background="#030303",
        surface="#121212",
        panel="#212121",
        success="#3EA6FF",
        warning="#FFC107",
        error="#FF4E45",
        dark=True,
    ),
    Theme(
        name="synthwave-84",
        primary="#FF7EDB",
        secondary="#36F9F6",
        accent="#FEDE5D",
        foreground="#F0E9FF",
        background="#1A1033",
        surface="#241B2F",
        panel="#34294F",
        success="#72F1B8",
        warning="#FEDE5D",
        error="#FE4450",
        dark=True,
    ),
    Theme(
        name="matrix",
        primary="#00FF41",
        secondary="#008F11",
        accent="#B6FFB0",
        foreground="#C8FFC8",
        background="#000000",
        surface="#0A140A",
        panel="#0F1F0F",
        success="#00FF41",
        warning="#D4FF00",
        error="#FF3B3B",
        dark=True,
    ),
    Theme(
        name="sakura",
        primary="#D6457A",
        secondary="#9A6FB0",
        accent="#F4A7B9",
        foreground="#3B2A33",
        background="#FFF5F7",
        surface="#FFE8EE",
        panel="#F9D5DF",
        success="#4E9F72",
        warning="#C98A1B",
        error="#C0392B",
        dark=False,
    ),
    Theme(
        name="vaporwave",
        primary="#01CDFE",
        secondary="#B967FF",
        accent="#FF71CE",
        foreground="#E8F7FF",
        background="#120B24",
        surface="#1D1338",
        panel="#2B1D52",
        success="#05FFA1",
        warning="#FFFB96",
        error="#FF5E7E",
        dark=True,
    ),
    Theme(
        name="amber-crt",
        primary="#FFB000",
        secondary="#CC7A00",
        accent="#FFD580",
        foreground="#FFCC66",
        background="#140C00",
        surface="#1F1400",
        panel="#2E1E00",
        success="#FFB000",
        warning="#FFE08A",
        error="#FF5500",
        dark=True,
    ),
]

# Orden del atajo `t`. El theme dinámico se genera a partir de la portada.
THEME_CYCLE = [
    WINAMP_THEME,
    "youtube-music",
    COVER_THEME,
    "synthwave-84",
    "vaporwave",
    "catppuccin-mocha",
    "tokyo-night",
    "dracula",
    "nord",
    "gruvbox",
    "matrix",
    "amber-crt",
    "sakura",
]


def cover_theme(palette: dict[str, str] | None) -> Theme:
    p = palette or {
        "primary": "#7AA2F7",
        "secondary": "#BB9AF7",
        "accent": "#F7768E",
        "background": "#11121A",
        "surface": "#1A1B26",
        "panel": "#24283B",
        "foreground": "#E0E3F0",
    }
    return Theme(name=COVER_THEME, dark=True, success="#9ECE6A", warning="#E0AF68",
                 error="#F7768E", **p)
