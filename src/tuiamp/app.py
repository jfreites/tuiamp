from __future__ import annotations

import time

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.theme import Theme
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from .api import SEARCH_FILTERS, SearchItem, YTMClient, extract_playlist_id
from .audio import AudioEngine, DownloadCache
from .config import LocalPlaylists, Settings
from .cover import cover_palette, fetch_cover
from .equalizer import BAND_LABELS, EQ_PRESETS, PREAMP, EQScale, EQSlider, clamp_db
from .lyrics import fetch_lyrics
from .models import Track
from .playqueue import PlayQueue
from .screens import (
    MODAL_CSS,
    NEW_PLAYLIST,
    Confirm,
    HelpScreen,
    OptionPicker,
    PlaylistPicker,
    TextPrompt,
)
from .themes import COVER_THEME, CUSTOM_THEMES, THEME_CYCLE, cover_theme, skin_defaults
from .widgets import CoverArt, HiResCover, LyricsView, TrackTable, Visualizer
from .winamp import LCDTime, Marquee, Slider, StreamInfo, WinTitle, total_time

FILTER_LABELS = {
    "songs": "Canciones",
    "albums": "Álbumes",
    "artists": "Artistas",
    "playlists": "Playlists",
    "videos": "Videos",
}

# id del botón → acción. Los de transporte imitan los de Winamp: |◀ ▶ ▌▌ ■ ▶| ▲
BUTTON_ACTIONS = {
    "btn-prev": "previous",
    "btn-play": "play",
    "btn-pause": "pause",
    "btn-stop": "stop",
    "btn-next": "next",
    "btn-eject": "focus_search",
    "btn-shuffle": "shuffle",
    "btn-repeat": "repeat",
    "btn-pl": "toggle_playlist",
    "btn-eq": "toggle_eq",
    "btn-eq-on": "eq_on",
    "btn-eq-auto": "eq_auto",
    "btn-eq-presets": "eq_presets",
    "btn-add": "focus_search",
    "btn-rem": "remove_from_queue",
    "btn-save": "save_queue",
}


def wa_button(label: str, id: str, classes: str = "wa-btn") -> Button:
    button = Button(label, id=id, classes=classes)
    button.can_focus = False  # un clic no debe robarle el foco a la playlist
    return button


class PlaylistItem(ListItem):
    def __init__(self, source: str, key: str, title: str, count: str = "") -> None:
        label = f"♫ {title}" + (f"  [dim]{count}[/dim]" if count else "")
        super().__init__(Label(label))
        self.source, self.key, self.title = source, key, title


class SectionItem(ListItem):
    def __init__(self, title: str) -> None:
        super().__init__(Label(f"[b]{title}[/b]"), disabled=True)


class TuiampApp(App):
    TITLE = "Tuiamp"
    CSS = """
    Screen { background: $face-dark; }
    .window { background: $face; border: outer $face-light; }
    #top { height: 13; }
    #main-window { width: 66; }
    #cover-window { width: 26; }
    #vis-window { width: 1fr; }
    #bottom { height: 1fr; }
    #playlist-window { width: 3fr; }
    #lyrics-window { width: 2fr; min-width: 30; }

    /* Ventana principal */
    #mw-top { height: 5; margin: 0 1; }
    #lcd { width: 27; background: $lcd-bg; border-right: vkey $face-light; }
    #mini-vis { height: 2; padding: 0 1; }
    #mw-right { padding-left: 1; }
    #marquee-box { height: 1; background: $lcd-bg; padding: 0 1; }
    StreamInfo { padding: 0 1; }
    #sliders { height: 2; margin-top: 1; }
    #vol { width: 1fr; }
    #bal { width: 10; margin: 0 1; }
    #seek { margin: 1 1 0 1; }
    #transport { height: 2; margin: 1 1 0 1; }
    #logo { width: 1fr; content-align: right middle; color: $title-stripe; text-style: bold italic; }

    /* Botones con relieve: sombra fina a la derecha y debajo; al pulsarlos desaparece. */
    .wa-btn {
        min-width: 4; height: 2; border: none; padding: 0 1; margin-right: 1;
        border-right: tall $face-dark; border-bottom: wide $face-dark;
        background: $btn-face; color: $btn-fg; text-style: bold;
    }
    .wa-btn:hover { background: $btn-face 75%; }
    .wa-btn.-active { border-right: tall $face; border-bottom: wide $face; }
    #transport .wa-btn { padding: 0; }  /* el line-pad de Button ya deja aire al texto */
    .wa-btn.-on { background: $lcd-bg; color: $lcd-fg; }
    #btn-pl, #btn-eq { width: 5; min-width: 5; padding: 0; margin: 0; }
    #btn-eq { margin-right: 1; }

    /* Ecualizador */
    #eq-window { width: 52; }
    #eq-bar { height: 2; margin: 0 1; }
    #eq-readout { width: 1fr; height: 1; background: $lcd-bg; color: $lcd-fg; padding: 0 1; margin-right: 1; }
    #btn-eq-presets { margin: 0; }
    #eq-sliders { height: 8; margin: 0 1; }

    /* Portada y visualización */
    #cover-window CoverArt, #cover-window HiResCover { height: 1fr; }
    #big-vis { height: 1fr; background: $lcd-bg; }

    /* Playlist editor */
    #tabs { height: 1fr; }
    #tabs Tabs { background: $face; }
    #tabs Underline > .underline--bar { color: $title-stripe; background: $face-light; }
    TabPane { padding: 0; }
    #search-bar { height: 3; background: $face; }
    #search-input { width: 1fr; }
    #search-filter { width: 20; }
    #playlist-list { width: 28; background: $lcd-bg; border-right: vkey $face-light; }
    TrackTable { height: 1fr; }
    #pl-footer { height: 2; background: $face; padding: 0 1; }
    #pl-time { width: 1fr; height: 1; content-align: right middle; color: $lcd-fg; }

    #lyrics { height: 1fr; background: $lcd-bg; }
    Footer { background: $face-dark; }
    """ + MODAL_CSS

    BINDINGS = [
        # Atajos clásicos de Winamp: Z X C V B
        Binding("z", "previous", "Anterior", show=False),
        Binding("x", "play", "Play", show=False),
        Binding("c", "pause", "Pausa", show=False),
        Binding("v", "stop", "Stop", show=False),
        Binding("b", "next", "Siguiente", show=False),
        Binding("space", "toggle_pause", "Play/Pausa"),
        Binding("n", "next", "Siguiente"),
        Binding("p", "previous", "Anterior"),
        Binding("left,comma", "seek(-5)", "−5s", show=False),
        Binding("right,full_stop", "seek(5)", "+5s", show=False),
        Binding("minus", "volume(-0.05)", "Vol −", show=False),
        Binding("equals_sign,plus", "volume(0.05)", "Vol +", show=False),
        Binding("left_square_bracket", "balance(-0.1)", "Bal ←", show=False),
        Binding("right_square_bracket", "balance(0.1)", "Bal →", show=False),
        Binding("s", "shuffle", "Shuffle", show=False),
        Binding("r", "repeat", "Repeat", show=False),
        Binding("slash", "focus_search", "Buscar"),
        Binding("l", "toggle_lyrics", "Letras"),
        Binding("o", "cycle_visualizer", "Visual"),
        Binding("t", "cycle_theme", "Skin"),
        Binding("e", "toggle_eq", "EQ"),
        Binding("E", "eq_presets", "Presets EQ", show=False),
        Binding("a", "enqueue", "Añadir", show=False),
        Binding("N", "enqueue_next", "Reproducir a continuación", show=False),
        Binding("g", "add_to_playlist", "Guardar en playlist", show=False),
        Binding("S", "save_queue", "Guardar cola", show=False),
        Binding("d,delete", "remove", "Quitar", show=False),
        Binding("J", "move(1)", "Bajar", show=False),
        Binding("K", "move(-1)", "Subir", show=False),
        Binding("1", "tab('queue')", "Playlist", show=False),
        Binding("2", "tab('search')", "Buscar", show=False),
        Binding("3", "tab('playlists')", "Biblioteca", show=False),
        Binding("escape", "focus_table", show=False),
        Binding("question_mark", "help", "Ayuda"),
        Binding("q", "quit", "Salir"),
    ]

    def __init__(self, client: YTMClient, image_widget: type | None = None, cell_aspect: float = 2.0) -> None:
        super().__init__()
        self.client = client
        self.image_widget = image_widget
        self.cell_aspect = cell_aspect  # alto/ancho de una celda: para que la portada sea cuadrada
        self.settings = Settings.load()
        self.local = LocalPlaylists()
        self.engine = AudioEngine(volume=self.settings.volume, balance=self.settings.balance)
        self._apply_eq(debounce=0)
        self.downloads = DownloadCache()
        self.queue = PlayQueue()
        self.queue.shuffle = self.settings.shuffle
        self.queue.repeat = self.settings.repeat
        self._token = 0
        self._retried = False
        self._failures = 0
        self._resolving = False
        self._stream_info = (0, 0, 0)
        self._open_playlist: PlaylistItem | None = None
        self._focus_input_next = False

    def get_theme_variable_defaults(self) -> dict[str, str]:
        # Variables del look Winamp (LCD, playlist, botones) para cualquier theme/skin.
        return {**super().get_theme_variable_defaults(), **skin_defaults(self.current_theme)}

    # ── Layout ─────────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            with Vertical(id="main-window", classes="window"):
                yield WinTitle("TUIAMP", closable=True)
                with Horizontal(id="mw-top"):
                    with Vertical(id="lcd"):
                        yield LCDTime(id="lcd-time")
                        yield Visualizer(self.engine, mode="bars", bar_width=1, gap=1, id="mini-vis")
                    with Vertical(id="mw-right"):
                        with Vertical(id="marquee-box"):
                            yield Marquee(id="marquee")
                        yield StreamInfo(id="stream-info")
                        with Horizontal(id="sliders"):
                            yield Slider("volume", "VOL", self.engine.volume, id="vol")
                            yield Slider("balance", "BAL", self.engine.balance, id="bal")
                            yield wa_button("EQ", "btn-eq")
                            yield wa_button("PL", "btn-pl", "wa-btn -on")
                yield Slider("seek", live=False, id="seek")
                with Horizontal(id="transport"):
                    yield wa_button("|◀", "btn-prev")
                    yield wa_button("▶", "btn-play")
                    yield wa_button("▌▌", "btn-pause")
                    yield wa_button("■", "btn-stop")
                    yield wa_button("▶|", "btn-next")
                    yield wa_button("▲", "btn-eject")
                    yield wa_button("SHUF", "btn-shuffle")
                    yield wa_button("REP", "btn-repeat")
                    yield Static("Tuiamp", id="logo")
            with Vertical(id="eq-window", classes="window"):
                yield WinTitle("TUIAMP EQUALIZER")
                with Horizontal(id="eq-bar"):
                    yield wa_button("ON", "btn-eq-on")
                    yield wa_button("AUTO", "btn-eq-auto")
                    yield Static("", id="eq-readout")
                    yield wa_button("PRESETS", "btn-eq-presets")
                with Horizontal(id="eq-sliders"):
                    yield EQSlider(PREAMP, "PRE", self.settings.eq_preamp, id="eq-pre")
                    yield EQScale()
                    for i, label in enumerate(BAND_LABELS):
                        yield EQSlider(i, label, self.settings.eq_bands[i], id=f"eq-{i}")
            with Vertical(id="cover-window", classes="window"):
                yield WinTitle("ALBUM ART")
                if self.image_widget:
                    yield HiResCover(self.image_widget, self.cell_aspect, id="cover")
                else:
                    yield CoverArt(self.cell_aspect, id="cover")
            with Vertical(id="vis-window", classes="window"):
                yield WinTitle("TUIAMP VISUALIZATION")
                yield Visualizer(self.engine, mode=self.settings.visualizer, id="big-vis")
        with Horizontal(id="bottom"):
            with Vertical(id="playlist-window", classes="window"):
                yield WinTitle("TUIAMP PLAYLIST EDITOR")
                with TabbedContent(id="tabs", initial="search"):
                    with TabPane("Playlist", id="queue"):
                        yield TrackTable("queue", compact=True, id="queue-table")
                    with TabPane("Buscar", id="search"):
                        with Horizontal(id="search-bar"):
                            yield Input(
                                placeholder="Canciones, álbumes, playlists… o pega una URL de playlist",
                                id="search-input",
                            )
                            yield Select(
                                [(FILTER_LABELS[f], f) for f in SEARCH_FILTERS],
                                value="songs",
                                allow_blank=False,
                                id="search-filter",
                            )
                        yield TrackTable("search", id="search-table")
                    with TabPane("Biblioteca", id="playlists"):
                        with Horizontal():
                            yield ListView(id="playlist-list")
                            yield TrackTable("playlist", id="playlist-table")
                with Horizontal(id="pl-footer"):
                    yield wa_button("+ADD", "btn-add")
                    yield wa_button("-REM", "btn-rem")
                    yield wa_button("SAVE", "btn-save")
                    yield Static("", id="pl-time")
            with Vertical(id="lyrics-window", classes="window"):
                yield WinTitle("LYRICS")
                yield LyricsView(id="lyrics")
        yield Footer()

    def on_mount(self) -> None:
        for theme in CUSTOM_THEMES:
            self.register_theme(theme)
        self.register_theme(cover_theme(None))
        self.theme = self.settings.theme if self.settings.theme in self.available_themes else "winamp-classic"
        self.theme_changed_signal.subscribe(self, self._on_theme_changed)

        self.query_one("#lyrics-window").display = self.settings.show_lyrics
        self.query_one("#eq-window").display = self.settings.show_eq
        # Ancho de ALBUM ART para que la portada (10 filas) salga cuadrada; +2 del marco.
        cover_rows = 10
        self.query_one("#cover-window").styles.width = round(cover_rows * self.cell_aspect) + 2
        self._update_eq_readout()
        self._sync_toggles()
        self._update_info()
        self.set_interval(0.25, self._tick)
        self.load_playlists()
        self.query_one("#search-input", Input).focus()
        if not self.client.authenticated:
            self.notify("Modo invitado: ejecuta `tuiamp auth` para ver tu biblioteca.", timeout=6)

    def on_unmount(self) -> None:
        self.engine.close()

    # ── Reproducción ───────────────────────────────────────────────────────
    def play_current(self) -> None:
        track = self.queue.current
        self.engine.stop()
        self._token += 1
        self._retried = False
        self._refresh_queue()
        self._update_info()
        if track is None:
            self.query_one(LyricsView).set_lyrics(None, "Sin reproducción")
            return
        if self.settings.eq_auto:
            self._load_track_eq(track)
        token = self._token
        self._resolving = True
        self.query_one(LyricsView).set_lyrics(None, "Buscando letra…")
        self.resolve_and_play(track, token)
        self.load_cover(track, token)
        self.load_lyrics(track, token)

    @work(thread=True, group="stream")
    def resolve_and_play(self, track: Track, token: int, refresh: bool = False) -> None:
        if refresh:
            self.downloads.discard(track.video_id)
        try:
            stream = self.client.stream(track.video_id, refresh=refresh)
        except Exception as exc:  # yt-dlp lanza excepciones muy variadas
            self.call_from_thread(self._track_failed, token, f"No se pudo obtener el audio: {exc}")
            return
        if token != self._token:
            return
        source = self.downloads.get(
            track.video_id, stream.url, stream.headers, self._url_refresher(track.video_id)
        )
        self.engine.play(source, duration=track.duration)
        self._resolving = False
        self._stream_info = (stream.kbps, stream.khz, stream.channels)
        self.call_from_thread(self._update_info)
        # Precarga la siguiente cuando termine la actual, para no competir por ancho de banda.
        while not source.done and token == self._token:
            time.sleep(0.5)
        upcoming = self.queue.peek_next()
        if token != self._token or not upcoming or upcoming.video_id == track.video_id:
            return
        try:
            nxt = self.client.stream(upcoming.video_id)
            self.downloads.get(
                upcoming.video_id, nxt.url, nxt.headers, self._url_refresher(upcoming.video_id)
            )
        except Exception:
            pass

    def _url_refresher(self, video_id: str):
        def refresh() -> tuple[str, dict[str, str]]:
            stream = self.client.stream(video_id, refresh=True)
            return stream.url, stream.headers

        return refresh

    def _track_failed(self, token: int, message: str) -> None:
        if token != self._token:
            return
        self._resolving = False
        self._failures += 1
        self.notify(message[:300], severity="error", timeout=6)
        if self._failures >= 3:
            self.notify("Demasiados errores seguidos; reproducción detenida.", severity="error")
            self._failures = 0
            self.engine.stop()
            return
        self._advance(auto=False)

    @work(thread=True, group="cover")
    def load_cover(self, track: Track, token: int) -> None:
        image = fetch_cover(track.thumbnail)
        palette = cover_palette(image) if image else None
        self.call_from_thread(self._apply_cover, token, image, palette)

    def _apply_cover(self, token: int, image, palette) -> None:
        if token != self._token:
            return
        self.query_one("#cover").set_image(image)
        self.register_theme(cover_theme(palette))
        if self.theme == COVER_THEME:
            self.mutate_reactive(App.theme)

    @work(thread=True, group="lyrics")
    def load_lyrics(self, track: Track, token: int) -> None:
        lyrics = fetch_lyrics(self.client, track)
        self.call_from_thread(self._apply_lyrics, token, lyrics)

    def _apply_lyrics(self, token: int, lyrics) -> None:
        if token == self._token:
            self.query_one(LyricsView).set_lyrics(lyrics, "" if lyrics else "Sin letra disponible")

    def _advance(self, auto: bool) -> None:
        if self.queue.next(auto=auto) is None:
            self.engine.stop()
            self._token += 1
            self._update_info()
            return
        self.play_current()

    def _tick(self) -> None:
        engine = self.engine
        if engine.finished:
            position, error = engine.position, engine.error
            engine.stop()
            track = self.queue.current
            if error and position < 2 and not self._retried and track:
                # La URL pudo expirar: pedimos una nueva una sola vez.
                self._retried = True
                self.resolve_and_play(track, self._token, refresh=True)
            else:
                if error and position < 2:
                    self._track_failed(self._token, f"Error de reproducción: {error}")
                    return
                self._failures = 0
                self._advance(auto=True)
        track = self.queue.current
        duration = float((track.duration if track else 0) or engine.duration)
        position = engine.position if engine.active else 0.0

        lcd = self.query_one(LCDTime)
        if track and (self._resolving or engine.buffering):
            lcd.state = "load"
        elif not engine.active:
            lcd.state = "stop"
        else:
            lcd.state = "pause" if engine.paused else "play"
        lcd.position, lcd.duration = position, duration
        lcd.refresh()
        self.query_one("#seek", Slider).set_value(position / duration if duration else 0.0)
        if engine.active:
            self.query_one(LyricsView).update_position(position, duration)

    # ── Acciones de reproducción ───────────────────────────────────────────
    def action_play(self) -> None:
        """Como la X de Winamp: reanuda si está en pausa; si no, (re)empieza la canción."""
        if self.engine.active and self.engine.paused:
            self.engine.toggle_pause()
        elif self.engine.active:
            self.engine.seek(0)
        elif self.queue.current:
            self.play_current()

    def action_pause(self) -> None:
        self.engine.toggle_pause()

    def action_stop(self) -> None:
        self.engine.stop()
        self._token += 1  # descarta descargas/letras en vuelo de esta canción
        self._resolving = False

    def action_toggle_pause(self) -> None:
        if not self.engine.active and self.queue.current:
            self.play_current()
        else:
            self.engine.toggle_pause()

    def action_next(self) -> None:
        self._advance(auto=False)

    def action_previous(self) -> None:
        if self.engine.position > 3:
            self.engine.seek(0)
        elif self.queue.previous() is not None:
            self.play_current()

    def action_seek(self, delta: float) -> None:
        if self.engine.active:
            self.engine.seek(self.engine.position + delta)

    def action_volume(self, delta: float) -> None:
        self._set_volume(self.engine.volume + delta)

    def _set_volume(self, value: float) -> None:
        self.engine.volume = round(min(max(value, 0.0), 1.0), 2)
        self.query_one("#vol", Slider).set_value(self.engine.volume)
        self.settings.volume = self.engine.volume
        self.settings.save()

    def action_balance(self, delta: float) -> None:
        self._set_balance(self.engine.balance + delta)

    def _set_balance(self, value: float) -> None:
        value = round(min(max(value, -1.0), 1.0), 2)
        self.engine.balance = 0.0 if abs(value) < 0.06 else value  # imán al centro
        self.query_one("#bal", Slider).set_value(self.engine.balance)
        self.settings.balance = self.engine.balance
        self.settings.save()

    @on(Slider.Changed)
    def _slider_changed(self, event: Slider.Changed) -> None:
        if event.slider.id == "vol":
            self._set_volume(event.value)
        elif event.slider.id == "bal":
            self._set_balance(event.value)
        elif event.slider.id == "seek" and self.engine.active:
            track = self.queue.current
            duration = (track.duration if track else 0) or self.engine.duration
            if duration:
                self.engine.seek(event.value * duration)

    @on(Button.Pressed)
    async def _button_pressed(self, event: Button.Pressed) -> None:
        action = BUTTON_ACTIONS.get(event.button.id or "")
        if action:
            await self.run_action(action)

    def action_shuffle(self) -> None:
        self.settings.shuffle = self.queue.toggle_shuffle()
        self.settings.save()
        self._sync_toggles()
        self._refresh_queue()
        self._update_info()

    def action_repeat(self) -> None:
        self.settings.repeat = self.queue.cycle_repeat()
        self.settings.save()
        self._sync_toggles()
        self._update_info()

    def _sync_toggles(self) -> None:
        """Los botones SHUF / REP / PL se "encienden" como los LEDs de Winamp."""
        self.query_one("#btn-shuffle", Button).set_class(self.queue.shuffle, "-on")
        repeat = self.query_one("#btn-repeat", Button)
        repeat.label = {"off": "REP", "all": "REP", "one": "REP1"}[self.queue.repeat]
        repeat.set_class(self.queue.repeat != "off", "-on")
        self.query_one("#btn-pl", Button).set_class(self.query_one("#playlist-window").display, "-on")
        self.query_one("#btn-eq", Button).set_class(self.query_one("#eq-window").display, "-on")
        self.query_one("#btn-eq-on", Button).set_class(self.settings.eq_on, "-on")
        self.query_one("#btn-eq-auto", Button).set_class(self.settings.eq_auto, "-on")

    # ── Vista ──────────────────────────────────────────────────────────────
    def action_toggle_lyrics(self) -> None:
        window = self.query_one("#lyrics-window")
        window.display = not window.display
        self.settings.show_lyrics = window.display
        self.settings.save()

    def action_toggle_playlist(self) -> None:
        window = self.query_one("#playlist-window")
        window.display = not window.display
        self._sync_toggles()

    # ── Ecualizador ────────────────────────────────────────────────────────
    def action_toggle_eq(self) -> None:
        window = self.query_one("#eq-window")
        window.display = not window.display
        self.settings.show_eq = window.display
        self.settings.save()
        self._sync_toggles()

    def action_eq_on(self) -> None:
        self.settings.eq_on = not self.settings.eq_on
        self._eq_changed()
        self.notify(f"Ecualizador {'activado' if self.settings.eq_on else 'desactivado'}", timeout=1.5)

    def action_eq_auto(self) -> None:
        self.settings.eq_auto = not self.settings.eq_auto
        if self.settings.eq_auto:
            self._remember_track_eq()
        self.settings.save()
        self._sync_toggles()

    def action_eq_presets(self) -> None:
        def chosen(name: str | None) -> None:
            if name:
                self.apply_eq_preset(name)

        self.push_screen(OptionPicker("Presets del ecualizador", list(EQ_PRESETS), self.settings.eq_preset), chosen)

    def apply_eq_preset(self, name: str) -> None:
        preamp, bands = EQ_PRESETS[name]
        self._set_eq_values(preamp, list(bands))
        self.settings.eq_preset = name
        self._eq_changed()
        self.notify(f"Preset EQ: {name}", timeout=1.5)

    def _set_eq_values(self, preamp: float, bands: list[float]) -> None:
        self.settings.eq_preamp = clamp_db(preamp)
        self.settings.eq_bands = [clamp_db(b) for b in bands]
        self.query_one("#eq-pre", EQSlider).set_value(self.settings.eq_preamp)
        for i, value in enumerate(self.settings.eq_bands):
            self.query_one(f"#eq-{i}", EQSlider).set_value(value)

    def _apply_eq(self, debounce: float = 0.3) -> None:
        s = self.settings
        self.engine.set_eq(s.eq_preamp, s.eq_bands, s.eq_on, debounce=debounce)

    def _eq_changed(self) -> None:
        """Tras cualquier cambio: audio (con debounce), AUTO, disco y botones."""
        self._apply_eq()
        self._remember_track_eq()
        self.settings.save()
        self._sync_toggles()
        self._update_eq_readout()

    def _remember_track_eq(self) -> None:
        track = self.queue.current
        if self.settings.eq_auto and track:
            self.settings.eq_per_track[track.video_id] = [self.settings.eq_preamp, *self.settings.eq_bands]

    def _load_track_eq(self, track: Track) -> None:
        saved = self.settings.eq_per_track.get(track.video_id)
        if saved:
            self._set_eq_values(saved[0], saved[1:])
            self.settings.eq_preset = ""
            self._apply_eq(debounce=0)
            self._update_eq_readout()

    def _update_eq_readout(self, slider: EQSlider | None = None) -> None:
        if slider is not None:
            name = "PREAMP" if slider.band == PREAMP else f"{BAND_LABELS[slider.band]}Hz"
            text = f"{name} {slider.value:+.1f} dB"
        else:
            text = self.settings.eq_preset or "Custom"
        if not self.settings.eq_on:
            text += " (off)"
        self.query_one("#eq-readout", Static).update(text)

    @on(EQSlider.Changed)
    def _eq_slider_changed(self, event: EQSlider.Changed) -> None:
        if event.slider.band == PREAMP:
            self.settings.eq_preamp = event.value
        else:
            self.settings.eq_bands[event.slider.band] = event.value
        self.settings.eq_preset = ""
        self._apply_eq()
        self._remember_track_eq()
        if event.final:
            self.settings.save()
        self._update_eq_readout(event.slider)

    def action_cycle_visualizer(self) -> None:
        vis = self.query_one("#big-vis", Visualizer)
        modes = Visualizer.MODES
        vis.mode = modes[(modes.index(vis.mode) + 1) % len(modes)]
        if vis.mode == "off":
            vis._strips = []
            vis.refresh()
        self.settings.visualizer = vis.mode
        self.settings.save()
        self.notify(f"Visualización: {vis.mode}", timeout=1.5)

    def action_cycle_theme(self) -> None:
        cycle = [t for t in THEME_CYCLE if t in self.available_themes]
        idx = cycle.index(self.theme) if self.theme in cycle else -1
        self.theme = cycle[(idx + 1) % len(cycle)]
        self.notify(f"Theme: {self.theme}", timeout=1.5)

    def _on_theme_changed(self, theme: Theme) -> None:
        if self.settings.theme != theme.name:
            self.settings.theme = theme.name
            self.settings.save()

    def action_tab(self, tab: str) -> None:
        tabs = self.query_one(TabbedContent)
        if tabs.active == tab:
            self._focus_tab(tab)
        tabs.active = tab  # TabActivated se encarga del foco

    def action_focus_search(self) -> None:
        tabs = self.query_one(TabbedContent)
        if tabs.active == "search":
            self.query_one("#search-input", Input).focus()
        else:
            self._focus_input_next = True
            tabs.active = "search"

    def action_focus_table(self) -> None:
        self._focus_tab(self.query_one(TabbedContent).active, prefer_table=True)

    def _focus_tab(self, tab: str, prefer_table: bool = False) -> None:
        if tab == "search" and self._focus_input_next:
            self._focus_input_next = False
            self.query_one("#search-input", Input).focus()
            return
        if tab == "search":
            table = self.query_one("#search-table", TrackTable)
            target = table if table.items or prefer_table else self.query_one("#search-input", Input)
        elif tab == "playlists":
            table = self.query_one("#playlist-table", TrackTable)
            target = table if self._open_playlist else self.query_one("#playlist-list", ListView)
        else:
            target = self.query_one("#queue-table", TrackTable)
        target.focus()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    @on(TabbedContent.TabActivated)
    def _tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id:
            self._focus_tab(event.pane.id)

    def _refresh_queue(self) -> None:
        self.query_one("#queue-table", TrackTable).set_items(self.queue.tracks, self.queue.index)

    def _update_info(self) -> None:
        track = self.queue.current
        marquee = self.query_one(Marquee)
        if track:
            marquee.set_text(f"{self.queue.index + 1}. {track.artist} - {track.title} ({track.length})")
        else:
            marquee.set_text("TUIAMP — pulsa / para buscar música, ? para la ayuda")
            self.query_one("#cover").set_image(None)
        info = self.query_one(StreamInfo)
        info.kbps, info.khz, info.channels = self._stream_info if track else (0, 0, 0)
        info.refresh()
        # Como el contador del playlist editor de Winamp: actual / duración total.
        total = sum(t.duration for t in self.queue.tracks)
        current = track.length if track else "0:00"
        self.query_one("#pl-time", Static).update(
            f"{len(self.queue.tracks)} pistas  {current}/{total_time(total)}"
        )

    # ── Búsqueda ───────────────────────────────────────────────────────────
    @on(Input.Submitted, "#search-input")
    def _search_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip():
            filt = self.query_one("#search-filter", Select).value
            self.run_search(event.value.strip(), str(filt))

    @on(Select.Changed, "#search-filter")
    def _filter_changed(self, event: Select.Changed) -> None:
        query = self.query_one("#search-input", Input).value.strip()
        if query:
            self.run_search(query, str(event.value))

    @work(thread=True, exclusive=True, group="search")
    def run_search(self, query: str, filt: str) -> None:
        self.call_from_thread(self.notify, f"Buscando “{query}”…", timeout=1.5)
        try:
            playlist_id = extract_playlist_id(query)
            if playlist_id:
                tracks = self.client.playlist_tracks(playlist_id)
                items: list = [SearchItem("song", t.title, t.artist, track=t) for t in tracks]
            else:
                items = self.client.search(query, filter=filt)
        except Exception as exc:
            self.call_from_thread(self.notify, f"Error en la búsqueda: {exc}", severity="error")
            return
        self.call_from_thread(self._show_search, items, bool(playlist_id))

    def _show_search(self, items: list[SearchItem], is_collection: bool = False) -> None:
        table = self.query_one("#search-table", TrackTable)
        table.is_collection = is_collection
        table.set_items(items)
        table.move_cursor(row=0)
        table.focus()
        if not items:
            self.notify("Sin resultados", severity="warning")

    # ── Selección en tablas ────────────────────────────────────────────────
    @on(TrackTable.RowSelected)
    def _row_selected(self, event: TrackTable.RowSelected) -> None:
        table = event.data_table
        assert isinstance(table, TrackTable)
        index = event.cursor_row
        if table.role == "queue":
            self.queue.jump(index)
            self.play_current()
        elif table.role == "playlist":
            tracks = [t for t in table.items if isinstance(t, Track)]
            self.queue.set(tracks, index)
            if self.queue.shuffle:
                self.notify("Shuffle activo: la cola se ha mezclado", timeout=2)
            self.play_current()
        elif table.role == "search":
            item = table.selected()
            if not isinstance(item, SearchItem):
                return
            if item.track and table.is_collection:
                # Resultados de una URL de playlist: se reproduce la playlist completa.
                tracks = [i.track for i in table.items if isinstance(i, SearchItem) and i.track]
                self.queue.set(tracks, tracks.index(item.track))
                self.play_current()
            elif item.track:
                self.queue.set([item.track])
                self.play_current()
                self.load_radio(item.track)
            elif item.kind == "artist":
                self.load_artist(item.browse_id, item.title)
            else:
                self.load_collection(item.browse_id, item.title)

    @work(thread=True, group="radio")
    def load_radio(self, seed: Track) -> None:
        try:
            tracks = self.client.radio(seed.video_id)
        except Exception:
            return
        self.call_from_thread(self._extend_radio, seed, tracks)

    def _extend_radio(self, seed: Track, tracks: list[Track]) -> None:
        if self.queue.current != seed or len(self.queue.tracks) != 1:
            return
        for t in tracks:
            if t.video_id != seed.video_id:
                self.queue.add(t)
        self._refresh_queue()
        self._update_info()

    @work(thread=True, exclusive=True, group="artist")
    def load_artist(self, channel_id: str, title: str) -> None:
        self.call_from_thread(self.notify, f"Cargando “{title}”…", timeout=1.5)
        try:
            name, tracks, releases = self.client.artist(channel_id)
        except Exception as exc:
            self.call_from_thread(self.notify, f"No se pudo cargar el artista: {exc}", severity="error")
            return
        self.call_from_thread(self._show_artist, name or title, tracks, releases)

    def _show_artist(self, name: str, tracks: list[Track], releases: list[SearchItem]) -> None:
        """Canciones del artista (Enter reproduce la lista entera) y debajo su discografía."""
        items: list[SearchItem] = [SearchItem("song", t.title, t.artist, track=t) for t in tracks]
        self._show_search(items + releases, is_collection=True)
        self.notify(f"{name}: {len(tracks)} canciones · {len(releases)} discos", timeout=3)

    @work(thread=True, group="collection")
    def load_collection(self, browse_id: str, title: str) -> None:
        self.call_from_thread(self.notify, f"Cargando “{title}”…", timeout=1.5)
        try:
            tracks = self.client.playlist_tracks(browse_id)
        except Exception as exc:
            self.call_from_thread(self.notify, f"No se pudo cargar: {exc}", severity="error")
            return
        self.call_from_thread(self._play_collection, tracks)

    def _play_collection(self, tracks: list[Track]) -> None:
        if not tracks:
            self.notify("La colección está vacía", severity="warning")
            return
        self.queue.set(tracks, 0)
        self.play_current()

    # ── Cola y playlists ───────────────────────────────────────────────────
    def _focused_table(self) -> TrackTable | None:
        return self.focused if isinstance(self.focused, TrackTable) else None

    def _target_track(self) -> Track | None:
        table = self._focused_table()
        return table.selected_track() if table else self.queue.current

    def action_enqueue(self, next_: bool = False) -> None:
        table = self._focused_table()
        track = table.selected_track() if table and table.role != "queue" else None
        if not track:
            return
        was_empty = self.queue.current is None
        (self.queue.add_next if next_ else self.queue.add)(track)
        self._refresh_queue()
        self._update_info()
        self.notify(f"{'A continuación' if next_ else 'Añadida a la cola'}: {track.title}", timeout=2)
        if was_empty:
            self.play_current()

    def action_enqueue_next(self) -> None:
        self.action_enqueue(next_=True)

    def action_remove(self) -> None:
        if isinstance(self.focused, ListView):
            item = self.focused.highlighted_child
            if isinstance(item, PlaylistItem) and item.source == "local":
                def done(ok: bool | None) -> None:
                    if ok:
                        self.local.delete(item.key)
                        self.load_playlists()
                self.push_screen(Confirm(f"¿Eliminar la playlist “{item.title}”?"), done)
            return
        table = self._focused_table()
        if not table or table.cursor_row < 0:
            return
        index = table.cursor_row
        if table.role == "queue":
            removing_current = index == self.queue.index
            self.queue.remove(index)
            if removing_current:
                self.play_current()
            self._refresh_queue()
            self._update_info()
        elif table.role == "playlist" and self._open_playlist and self._open_playlist.source == "local":
            self.local.remove(self._open_playlist.key, index)
            self.open_playlist(self._open_playlist)

    def action_remove_from_queue(self) -> None:
        """Botón -REM: quita la pista seleccionada en la playlist."""
        self.query_one(TabbedContent).active = "queue"
        table = self.query_one("#queue-table", TrackTable)
        table.focus()
        if table.items:
            self.call_after_refresh(self.action_remove)

    def action_move(self, delta: int) -> None:
        table = self._focused_table()
        if table and table.role == "queue":
            new = self.queue.move(table.cursor_row, delta)
            self._refresh_queue()
            table.move_cursor(row=new)
            self._update_info()

    def action_add_to_playlist(self) -> None:
        track = self._target_track()
        if not track:
            self.notify("Selecciona una canción primero", severity="warning")
            return

        def chosen(name: str | None) -> None:
            if name == NEW_PLAYLIST:
                self.push_screen(TextPrompt("Nueva playlist", "Nombre"), created)
            elif name:
                added = self.local.add(name, track)
                self.notify(f"{'Guardada en' if added else 'Ya estaba en'} “{name}”", timeout=2)
                self._reload_if_open(name)

        def created(name: str | None) -> None:
            if name:
                self.local.create(name, [track])
                self.notify(f"Playlist “{name}” creada", timeout=2)
                self.load_playlists()

        self.push_screen(PlaylistPicker(f"Guardar “{track.title}” en…", self.local.names()), chosen)

    def action_save_queue(self) -> None:
        if not self.queue.tracks:
            self.notify("La cola está vacía", severity="warning")
            return

        def created(name: str | None) -> None:
            if name:
                self.local.create(name, self.queue.tracks)
                self.notify(f"Cola guardada como “{name}”", timeout=2)
                self.load_playlists()

        self.push_screen(TextPrompt("Guardar cola como playlist", "Nombre"), created)

    def _reload_if_open(self, name: str) -> None:
        if self._open_playlist and self._open_playlist.source == "local" and self._open_playlist.key == name:
            self.open_playlist(self._open_playlist)

    @work(thread=True, exclusive=True, group="playlists")
    def load_playlists(self) -> None:
        remote = []
        try:
            remote = self.client.library_playlists()
        except Exception as exc:
            self.call_from_thread(self.notify, f"No se pudo leer tu biblioteca: {exc}", severity="warning")
        self.call_from_thread(self._show_playlists, remote)

    async def _show_playlists(self, remote) -> None:
        view = self.query_one("#playlist-list", ListView)
        await view.clear()
        items: list[ListItem] = [SectionItem("LOCALES")]
        names = self.local.names()
        items += [PlaylistItem("local", n, n, str(len(self.local.get(n)))) for n in names]
        if not names:
            items.append(SectionItem("[dim]  (S guarda la cola)[/dim]"))
        items.append(SectionItem("YOUTUBE MUSIC"))
        if remote:
            items += [PlaylistItem("ytm", p.playlist_id, p.title, p.count) for p in remote]
        else:
            items.append(SectionItem("[dim]  tuiamp auth para ver[/dim]"))
        await view.extend(items)
        # Evita que el cursor arranque sobre un encabezado deshabilitado.
        view.index = next((i for i, it in enumerate(items) if isinstance(it, PlaylistItem)), None)

    @on(ListView.Selected, "#playlist-list")
    def _playlist_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, PlaylistItem):
            self.open_playlist(event.item)

    def open_playlist(self, item: PlaylistItem) -> None:
        self._open_playlist = item
        if item.source == "local":
            self._show_playlist_tracks(item, self.local.get(item.key))
        else:
            self._fetch_remote_playlist(item)

    @work(thread=True, exclusive=True, group="playlist-tracks")
    def _fetch_remote_playlist(self, item: PlaylistItem) -> None:
        try:
            tracks = self.client.playlist_tracks(item.key)
        except Exception as exc:
            self.call_from_thread(self.notify, f"No se pudo cargar: {exc}", severity="error")
            return
        self.call_from_thread(self._show_playlist_tracks, item, tracks)

    def _show_playlist_tracks(self, item: PlaylistItem, tracks: list[Track]) -> None:
        if self._open_playlist is not item:
            return
        table = self.query_one("#playlist-table", TrackTable)
        table.set_items(tracks)
        table.focus()
