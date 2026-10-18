# Tuiamp

> *It really whips the llama's ass…* ahora en tu terminal.

**Tuiamp** es un reproductor de **YouTube Music** para la terminal con el look de **Winamp 2.x**, hecho con [Textual](https://textual.textualize.io/).

- 🦙 **Look Winamp**: ventana principal con display LCD (reloj grande, mini-analizador, marquee que se desplaza, `kbps / kHz / stereo`), sliders de volumen y balance, seek bar y botones `|◀ ▶ ▌▌ ■ ▶| ▲`, *playlist editor* verde sobre negro y los atajos clásicos **Z X C V B**.
- 🎚️ **Ecualizador**: la ventana *TUIAMP EQUALIZER* de Winamp, con preamp y 10 bandas (60 Hz – 16 kHz, ±12 dB), botones `ON` / `AUTO` y presets (Rock, Pop, Classical, Flat…). Se aplica con filtros de ffmpeg y los cambios entran con un fundido, sin cortes.
- 🎨 **Skins**: `winamp-classic` (el de siempre, con el espectro verde→rojo original), 6 skins propios, todos los themes de Textual y **`cover-art`**, que genera la paleta a partir de la portada de cada canción.
- 📊 **Visualizador real**: FFT del audio que está sonando, en 3 modos: barras con picos, espejo y osciloscopio en braille.
- 🖼️ **Portadas**: en alta resolución con Sixel o Kitty graphics si la terminal lo soporta; si no, con bloques de media celda en truecolor.
- 🎤 **Letras sincronizadas**: de YouTube Music (LyricFind), con LRCLIB como respaldo.
- 🎸 **Artistas**: busca con el filtro «Artistas» y abre la ficha de uno para ver todas sus canciones y su discografía completa (álbumes, singles y EPs).
- 📜 **Playlists**: locales (guardadas en disco), tu biblioteca de YouTube Music (con login), álbumes, URLs pegadas y radio automática a partir de cualquier canción.
- 🔊 **Audio estable**: el audio se descarga completo con reintentos por bloque, así que un corte de red no provoca saltos.

## Requisitos

- Python ≥ 3.12 y [uv](https://docs.astral.sh/uv/)
- `ffmpeg` (`brew install ffmpeg`)

## Instalación y uso

```bash
uv sync
uv run tuiamp
```

Para instalarlo como comando global:

```bash
uv tool install .
```

### Iniciar sesión (opcional)

Sin cuenta puedes buscar, reproducir, escuchar radios y abrir playlists públicas. Para ver tu biblioteca y tus «Canciones que te gustan»:

```bash
uv run tuiamp auth
```

Abre music.youtube.com con tu sesión iniciada, ve a DevTools → Network, copia los *Request Headers* de una petición POST a `/browse` y pégalos en la terminal. Con `tuiamp logout` se borran.

### Opciones

| Flag | Descripción |
|---|---|
| `--cover auto` | (por defecto) Sixel/Kitty en alta resolución si la terminal lo soporta |
| `--cover halfblock` | Fuerza el render con bloques de media celda |

## Atajos

| Tecla | Acción |
|---|---|
| `z` `x` `c` `v` `b` | Anterior · Play · Pausa · Stop · Siguiente (como en Winamp) |
| `space` · `n` / `p` | Play/pausa · siguiente / anterior |
| `←` `→` / `,` `.` | Retroceder / avanzar 5 s |
| `-` / `+` · `[` / `]` | Volumen · balance |
| `s` / `r` | Shuffle / repeat (off → all → one) |
| `1` `2` `3` | Playlist / Buscar / Biblioteca |
| `/` (o el botón `▲`) | Buscar; también acepta URLs de playlists y álbumes |
| `Enter` | Reproducir (en una canción buscada inicia una radio; en un artista muestra sus canciones y discos) |
| `a` / `N` | Añadir a la playlist / reproducir a continuación |
| `g` | Guardar la canción en una playlist local |
| `S` | Guardar la playlist actual |
| `d` / `Supr` | Quitar de la playlist (en la Biblioteca, elimina la playlist local) |
| `J` / `K` | Mover en la playlist |
| `e` · `E` | Mostrar/ocultar el ecualizador · elegir preset |
| `l` · `o` | Mostrar/ocultar letras · modo de visualización |
| `t` | Siguiente skin (`ctrl+p` → «Change theme» para verlos todos) |
| `?` · `q` | Ayuda · salir |

Con el ratón: clic en el reloj para alternar transcurrido/restante (como en Winamp), arrastrar VOL, BAL y la barra de posición, `PL` / `EQ` para mostrar u ocultar el playlist editor o el ecualizador, arrastrar las bandas del EQ (la rueda del ratón las ajusta de 1 en 1 dB), y `✕` en la barra de título para salir.

## Arquitectura

```
src/tuiamp/
├── __init__.py   CLI (tuiamp, auth, logout)
├── app.py        App de Textual: ventanas, atajos, playlist y biblioteca
├── winamp.py     Piezas del look Winamp: barra de título, LCD, marquee y sliders
├── equalizer.py  Ventana del ecualizador: sliders verticales, escala y presets
├── audio.py      Descarga con reintentos → ffmpeg → PCM → sounddevice, más el FFT
├── api.py        ytmusicapi (búsqueda, artistas, álbumes, playlists, radio) y yt-dlp (URL del stream)
├── lyrics.py     Letras de YouTube Music y LRCLIB, con parser LRC
├── cover.py      Portadas: caché, medios bloques, Sixel/Kitty y paleta dinámica
├── themes.py     Skins (incluido winamp-classic) y variables del look para cualquier theme
├── widgets.py    Visualizer, CoverArt/HiResCover, LyricsView y TrackTable
├── screens.py    Modales (prompt, selector de playlist, confirmación, ayuda)
├── playqueue.py  Playlist en reproducción con shuffle y repeat
└── config.py     Ajustes y playlists locales (~/.config/tuiamp)
tests/
├── test_equalizer.py  Pruebas headless (app.run_test) del EQ: ventana, presets, ON/AUTO y persistencia
└── test_artist.py     Búsqueda por artista con un cliente falso: ficha, cola completa y discos
```

**Audio.** Un hilo descarga el stream completo en memoria con peticiones `Range` de 1 MiB. Si una conexión se cae, reintenta ese bloque desde el byte exacto, y si YouTube responde 403 pide una URL nueva y continúa. ffmpeg decodifica desde memoria a PCM, que se reproduce con sounddevice. Tener las muestras en Python permite dibujar el espectro real. El seek es casi instantáneo y la siguiente canción se precarga.

**Ecualizador.** El preamp y las bandas se traducen a un filtro `-af` de ffmpeg (`volume=…dB` más un `equalizer=f=…:t=o:w=1:g=…` por cada banda distinta de 0). Al mover un slider, tras 300 ms sin cambios se arranca un segundo ffmpeg con el filtro nuevo en la posición actual; cuando alcanza lo que está sonando se alinea a la muestra y sustituye al anterior con un fundido de 60 ms, así que no hay silencio ni salto. Con `AUTO` encendido, cada canción recuerda su EQ y lo recupera al volver a sonar. El estado se guarda en `settings.json`.

## Pruebas

```bash
TUIAMP_TEST_HOME=/tmp/tuiamp-test uv run --with pytest pytest tests
```

Usan `app.run_test` sin terminal ni red, con el volumen a 0 y la configuración en `TUIAMP_TEST_HOME` (o un directorio temporal), nunca en `~/.config`. Las capturas SVG quedan en `$TUIAMP_TEST_HOME/snapshots`.

Los ajustes se guardan en `~/.config/tuiamp/settings.json` (al primer arranque se copian los de `~/.config/ytmusic-tui` si existen), y las portadas se cachean en `~/.cache/tuiamp/covers`.
