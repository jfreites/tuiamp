"""Tuiamp: reproductor de YouTube Music para la terminal, con alma de Winamp."""

from __future__ import annotations

import argparse
import shutil
import sys

__version__ = "0.2.0"


def main() -> None:
    parser = argparse.ArgumentParser(prog="tuiamp", description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("auth", help="Configura tu cuenta pegando los headers del navegador")
    sub.add_parser("logout", help="Elimina las credenciales guardadas")
    parser.add_argument(
        "--cover",
        choices=("auto", "halfblock"),
        default="auto",
        help="auto = Sixel/Kitty en alta resolución si la terminal lo soporta",
    )
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()

    from .config import AUTH_FILE

    if args.command == "auth":
        import ytmusicapi

        AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        print("Abre music.youtube.com con tu sesión iniciada, DevTools → Network,")
        print("copia los 'Request Headers' de una petición POST a /browse y pégalos aquí.")
        print("Termina con una línea vacía (Enter dos veces o Ctrl-D).\n")
        ytmusicapi.setup(filepath=str(AUTH_FILE))
        print(f"\nCredenciales guardadas en {AUTH_FILE}")
        return
    if args.command == "logout":
        AUTH_FILE.unlink(missing_ok=True)
        print("Credenciales eliminadas.")
        return

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg no está instalado. En macOS: brew install ffmpeg")

    from .api import YTMClient
    from .app import TuiampApp
    from .cover import detect_graphics_widget, terminal_cell_aspect

    # La detección de gráficos tiene que ocurrir antes de que Textual tome la terminal.
    image_widget = detect_graphics_widget() if args.cover == "auto" else None
    cell_aspect = terminal_cell_aspect() if args.cover == "auto" else 2.0

    print("Conectando con YouTube Music…", flush=True)
    try:
        client = YTMClient()
    except Exception as exc:
        sys.exit(f"No se pudo conectar con YouTube Music: {exc}")
    TuiampApp(client, image_widget, cell_aspect).run()
