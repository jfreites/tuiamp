from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

# Va en el CSS de la App: el DEFAULT_CSS de una Screen se "scopea" con el nombre de
# la clase y los selectores `ModalScreen …` dejarían de coincidir.
MODAL_CSS = """
ModalScreen { align: center middle; background: $face-dark 70%; }
ModalScreen > Vertical {
    width: 60; height: auto; max-height: 90%;
    padding: 1 2; border: outer $face-light; background: $face;
}
HelpScreen > Vertical { width: 74; }
ModalScreen .title { text-style: bold; color: $title-stripe; margin-bottom: 1; }
ModalScreen OptionList { height: auto; max-height: 20; background: $lcd-bg; color: $pl-normal; }
ModalScreen Input { background: $lcd-bg; color: $pl-normal; }
ModalScreen .hint { color: $text-muted; margin-top: 1; }
"""

NEW_PLAYLIST = "__new__"


class TextPrompt(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancelar")]

    def __init__(self, title: str, placeholder: str = "", value: str = "") -> None:
        super().__init__()
        self._title, self._placeholder, self._value = title, placeholder, value

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._title, classes="title")
            yield Input(value=self._value, placeholder=self._placeholder)
            yield Label("Enter para aceptar · Esc para cancelar", classes="hint")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)


class PlaylistPicker(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancelar")]

    def __init__(self, title: str, names: list[str]) -> None:
        super().__init__()
        self._title, self._names = title, names

    def compose(self) -> ComposeResult:
        options = [Option(f"♫  {n}", id=n) for n in self._names]
        options.append(Option("＋ Nueva playlist…", id=NEW_PLAYLIST))
        with Vertical():
            yield Label(self._title, classes="title")
            yield OptionList(*options)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)


class OptionPicker(ModalScreen[str | None]):
    """Lista sencilla de opciones (p. ej. los presets del ecualizador)."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancelar")]

    def __init__(self, title: str, options: list[str], current: str = "") -> None:
        super().__init__()
        self._title, self._options, self._current = title, options, current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._title, classes="title")
            yield OptionList(*[Option(o, id=o) for o in self._options])

    def on_mount(self) -> None:
        if self._current in self._options:
            self.query_one(OptionList).highlighted = self._options.index(self._current)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)


class Confirm(ModalScreen[bool]):
    BINDINGS = [
        Binding("y,s,enter", "dismiss(True)", "Sí"),
        Binding("n,escape", "dismiss(False)", "No"),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._question, classes="title")
            yield Label("[b]s[/b] / Enter = sí · [b]n[/b] / Esc = no", classes="hint")


HELP_TEXT = """\
[b]Reproducción[/b] (los clásicos de Winamp)
  z x c v b    Anterior · Play · Pausa · Stop · Siguiente
  space        Play / pausa      n / p   Siguiente / anterior
  ← → , .      Retroceder / avanzar 5 s
  - / +        Volumen           [ / ]   Balance
  s            Shuffle           r       Repeat (off → all → one)

[b]Playlist editor[/b]
  1 2 3        Playlist / Buscar / Biblioteca
  /            Buscar (pega una URL de playlist para abrirla)
               Filtro Artistas: Enter abre sus canciones y discos
  Enter        Reproducir (canción buscada = inicia radio)
  a / N        Añadir a la playlist / reproducir a continuación
  g            Guardar en una playlist local
  S            Guardar la playlist actual
  d / Supr     Quitar        J / K   Mover

[b]Ecualizador[/b]
  e            Mostrar / ocultar la ventana EQ (o el botón EQ)
  E            Elegir preset (Rock, Pop, Classical, Flat…)
  Arrastra las bandas o usa la rueda (±1 dB) · ON activa · AUTO
  guarda el EQ de cada canción y lo recupera al volver a sonar

[b]Vista[/b]
  l            Letras          o   Modo de visualización
  t            Siguiente skin  ctrl+p  todos los skins
  Clic en el reloj: tiempo restante · arrastra VOL, BAL y la barra
  q            Salir
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,question_mark,q", "dismiss(None)", "Cerrar")]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Tuiamp · atajos de teclado", classes="title")
            yield Label(HELP_TEXT)
