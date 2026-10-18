"""Motor de audio: descarga → ffmpeg decodifica a PCM → sounddevice lo reproduce.

El audio se descarga completo en memoria con peticiones Range y reintentos, en lugar
de dejar que ffmpeg lo lea por HTTP: con backpressure la conexión quedaba inactiva,
YouTube la cortaba y la reconexión de ffmpeg producía saltos audibles.

Tener las muestras PCM en Python nos permite calcular el espectro (FFT) real
para el visualizador, en lugar de una animación falsa.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable

import httpx
import numpy as np
import sounddevice as sd

SAMPLE_RATE = 48_000
CHANNELS = 2
FRAME_BYTES = CHANNELS * 4  # float32
SCOPE_FRAMES = 4096
FFT_SIZE = 2048


class PCMBuffer:
    """Cola de bloques PCM con backpressure: el lector se bloquea si está llena."""

    def __init__(self, max_frames: int) -> None:
        self.max_frames = max_frames
        self._chunks: deque[np.ndarray] = deque()
        self._frames = 0
        self._cond = threading.Condition()
        self.closed = False

    def put(self, chunk: np.ndarray) -> bool:
        with self._cond:
            while self._frames >= self.max_frames and not self.closed:
                self._cond.wait(0.1)
            if self.closed:
                return False
            self._chunks.append(chunk)
            self._frames += len(chunk)
            return True

    def get(self, n: int) -> np.ndarray:
        parts: list[np.ndarray] = []
        need = n
        with self._cond:
            while need > 0 and self._chunks:
                chunk = self._chunks[0]
                if len(chunk) <= need:
                    parts.append(self._chunks.popleft())
                    need -= len(chunk)
                else:
                    parts.append(chunk[:need])
                    self._chunks[0] = chunk[need:]
                    need = 0
            self._frames -= n - need
            self._cond.notify_all()
        if not parts:
            return np.zeros((0, CHANNELS), dtype=np.float32)
        return parts[0] if len(parts) == 1 else np.concatenate(parts)

    def discard(self, n: int) -> int:
        """Tira hasta `n` frames del principio sin copiarlos. Devuelve cuántos tiró."""
        dropped = 0
        with self._cond:
            while dropped < n and self._chunks:
                chunk = self._chunks[0]
                take = min(len(chunk), n - dropped)
                if take == len(chunk):
                    self._chunks.popleft()
                else:
                    self._chunks[0] = chunk[take:]
                dropped += take
            self._frames -= dropped
            self._cond.notify_all()
        return dropped

    @property
    def frames(self) -> int:
        return self._frames

    def close(self) -> None:
        with self._cond:
            self.closed = True
            self._chunks.clear()
            self._frames = 0
            self._cond.notify_all()


class AudioDownload:
    """Descarga el audio completo en memoria, por bloques Range, reintentando cada bloque.

    Si la conexión se cae, se vuelve a pedir desde el byte exacto donde quedó:
    nunca se pierde ni se salta audio, como mucho hay una breve espera.
    """

    CHUNK = 1 << 20  # 1 MiB por petición
    MAX_RETRIES = 6

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        refresh: Callable[[], tuple[str, dict[str, str]]] | None = None,
    ) -> None:
        self.url = url
        self.headers = dict(headers or {})
        self._refresh = refresh  # pide una URL nueva si YouTube responde 403
        self.data = bytearray()
        self.total: int | None = None
        self.done = False
        self.error: str | None = None
        self._cond = threading.Condition()
        self._cancelled = False
        threading.Thread(target=self._run, daemon=True).start()

    @property
    def failed(self) -> bool:
        return self.error is not None

    def cancel(self) -> None:
        with self._cond:
            self._cancelled = True
            self._cond.notify_all()

    def read(self, offset: int, size: int) -> bytes | None:
        """Bloquea hasta tener datos en `offset`. b"" = fin del archivo, None = cancelado/error."""
        with self._cond:
            while len(self.data) <= offset and not (self.done or self._cancelled):
                self._cond.wait(0.5)
            if self._cancelled or (self.error and len(self.data) <= offset):
                return None
            return bytes(self.data[offset: offset + size])

    def _run(self) -> None:
        failures = 0
        refreshes = 0
        with httpx.Client(timeout=15, follow_redirects=True) as http:
            while not self._cancelled:
                offset = len(self.data)
                end = offset + self.CHUNK - 1
                try:
                    resp = http.get(
                        self.url, headers={**self.headers, "Range": f"bytes={offset}-{end}"}
                    )
                    if resp.status_code not in (200, 206):
                        raise httpx.HTTPStatusError(
                            f"HTTP {resp.status_code}", request=resp.request, response=resp
                        )
                    if self.total is None:
                        match = re.search(r"/(\d+)$", resp.headers.get("content-range", ""))
                        self.total = int(match.group(1)) if match else None
                    with self._cond:
                        self.data += resp.content
                        if resp.status_code == 200 or not resp.content or (
                            self.total is not None and len(self.data) >= self.total
                        ):
                            self.done = True
                        self._cond.notify_all()
                    failures = 0
                    if self.done:
                        return
                except httpx.HTTPStatusError as exc:
                    # 403: URL expirada o rechazada. Con una URL nueva se sigue desde
                    # el mismo byte, así que la canción no se corta ni se reinicia.
                    if self._refresh and refreshes < 2:
                        refreshes += 1
                        try:
                            self.url, self.headers = self._refresh()
                            continue
                        except Exception:
                            pass
                    self._fail(str(exc))
                    return
                except httpx.HTTPError as exc:
                    failures += 1
                    if failures > self.MAX_RETRIES:
                        self._fail(f"Conexión perdida: {exc}")
                        return
                    time.sleep(min(0.5 * 2 ** failures, 8))

    def _fail(self, message: str) -> None:
        with self._cond:
            self.error = message
            self.done = True
            self._cond.notify_all()


class DownloadCache:
    """Mantiene las últimas descargas (actual + precargadas) para no repetirlas."""

    def __init__(self, size: int = 4) -> None:
        self.size = size
        self._items: OrderedDict[str, AudioDownload] = OrderedDict()
        self._lock = threading.Lock()

    def get(
        self,
        key: str,
        url: str,
        headers: dict[str, str] | None = None,
        refresh: Callable[[], tuple[str, dict[str, str]]] | None = None,
    ) -> AudioDownload:
        with self._lock:
            item = self._items.get(key)
            if item and not item.failed and item.url == url:
                self._items.move_to_end(key)
                return item
            if item:
                item.cancel()
            item = AudioDownload(url, headers, refresh)
            self._items[key] = item
            while len(self._items) > self.size:
                _, old = self._items.popitem(last=False)
                old.cancel()
            return item

    def discard(self, key: str) -> None:
        with self._lock:
            item = self._items.pop(key, None)
        if item:
            item.cancel()


# ── Ecualizador ───────────────────────────────────────────────────────────────
# Las 10 bandas del EQ de Winamp 2.x, con su rango de ±12 dB.
EQ_BANDS = (60, 170, 310, 600, 1_000, 3_000, 6_000, 12_000, 14_000, 16_000)
EQ_RANGE = 12.0
XFADE_FRAMES = int(0.06 * SAMPLE_RATE)  # fundido al cambiar de filtro: sin clics ni saltos


def eq_filter(preamp: float, bands: list[float] | tuple[float, ...]) -> str | None:
    """Cadena `-af` de ffmpeg para el EQ, o None si es plano (sin coste de CPU)."""
    parts = []
    if abs(preamp) >= 0.05:
        parts.append(f"volume={preamp:+.1f}dB")
    for freq, gain in zip(EQ_BANDS, bands, strict=False):
        if abs(gain) >= 0.05:
            parts.append(f"equalizer=f={freq}:t=o:w=1:g={gain:+.1f}")
    return ",".join(parts) or None


class _Pipeline:
    """Un ffmpeg decodificando desde `start_frame`, con su cola de PCM."""

    def __init__(self, proc: subprocess.Popen, buf: PCMBuffer, start_frame: int, af: str | None) -> None:
        self.proc, self.buf, self.start_frame, self.af = proc, buf, start_frame, af
        self.eof = False
        self.error: str | None = None
        self.dropped = 0  # frames ya descartados al alinearlo con la reproducción

    def close(self) -> None:
        self.buf.close()
        try:
            self.proc.kill()
        except OSError:
            pass


class AudioEngine:
    def __init__(self, volume: float = 0.8, balance: float = 0.0, buffer_seconds: float = 8.0) -> None:
        self.volume = volume
        self.balance = balance  # -1 = izquierda, 0 = centro, 1 = derecha
        self._buffer_frames = int(buffer_seconds * SAMPLE_RATE)
        self._lock = threading.RLock()
        self._pipe: _Pipeline | None = None
        # Cambio de EQ en caliente: un ffmpeg nuevo se prepara en paralelo (`_pending`)
        # y, cuando alcanza la posición actual, sustituye al viejo (`_fading`) con un fundido.
        self._pending: _Pipeline | None = None
        self._fading: _Pipeline | None = None
        self._fade_pos = 0
        self._af: str | None = None
        self._eq_timer: threading.Timer | None = None
        self._source: AudioDownload | None = None
        self._frames_played = 0
        self.paused = False
        self.finished = False
        self.buffering = False
        self.duration: float = 0.0
        self.underruns = 0  # bloques que la tarjeta pidió y no llegaron a tiempo
        self.starved = 0  # bloques sin datos porque la red/ffmpeg no alcanzó
        self._scope = np.zeros(SCOPE_FRAMES, dtype=np.float32)
        self._window = np.hanning(FFT_SIZE).astype(np.float32)
        self._freqs = np.fft.rfftfreq(FFT_SIZE, 1 / SAMPLE_RATE)
        self._stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=1024,
            latency="high",  # más margen frente a pausas del GIL mientras la UI dibuja
            callback=self._callback,
        )
        self._stream.start()

    # ── API pública ────────────────────────────────────────────────────────
    @property
    def active(self) -> bool:
        return self._pipe is not None

    @property
    def error(self) -> str | None:
        pipe = self._pipe
        return pipe.error if pipe else None

    @property
    def position(self) -> float:
        return self._frames_played / SAMPLE_RATE

    @property
    def eq_filter(self) -> str | None:
        return self._af

    def play(self, source: AudioDownload, duration: float = 0.0, start: float = 0.0) -> None:
        with self._lock:
            self._source = source
            self.duration = duration
            self.paused = False
            self._start(start)

    def seek(self, position: float) -> None:
        with self._lock:
            if not self._source:
                return
            if self.duration:
                position = min(position, max(self.duration - 1, 0))
            self._start(max(position, 0.0))

    def set_eq(self, preamp: float, bands: list[float], enabled: bool = True, debounce: float = 0.3) -> None:
        """Cambia el EQ. Si algo suena, se aplica tras `debounce` s sin más cambios."""
        af = eq_filter(preamp, bands) if enabled else None
        with self._lock:
            if af == self._af:
                return
            self._af = af
            if self._eq_timer is not None:
                self._eq_timer.cancel()
                self._eq_timer = None
            if self._pipe is None:
                return  # se usará en el próximo play/seek
            if debounce <= 0:
                self._swap_filter()
                return
            self._eq_timer = threading.Timer(debounce, self._swap_filter)
            self._eq_timer.daemon = True
            self._eq_timer.start()

    def toggle_pause(self) -> None:
        if self.active:
            self.paused = not self.paused

    def stop(self) -> None:
        with self._lock:
            self._kill()
            self._source = None
            self._frames_played = 0
            self.finished = False

    def close(self) -> None:
        self.stop()
        self._stream.stop()
        self._stream.close()

    def waveform(self, n: int) -> np.ndarray:
        return self._scope[-n:].copy()

    def spectrum(self, bands: int, fmin: float = 40.0, fmax: float = 16_000.0) -> np.ndarray:
        """Magnitudes por banda (escala logarítmica de frecuencias), normalizadas a 0..1."""
        if bands <= 0:
            return np.zeros(0, dtype=np.float32)
        samples = self._scope[-FFT_SIZE:] * self._window
        mag = np.abs(np.fft.rfft(samples)) / (self._window.sum() / 2)
        edges = np.geomspace(fmin, fmax, bands + 1)
        idx = np.searchsorted(self._freqs, edges)
        out = np.empty(bands, dtype=np.float32)
        for i in range(bands):
            lo = idx[i]
            hi = max(idx[i + 1], lo + 1)
            out[i] = mag[lo:hi].max()
        centers = np.sqrt(edges[:-1] * edges[1:])
        # La música tiene espectro "rosa" (cae ~3 dB/octava): lo compensamos.
        db = 20 * np.log10(out + 1e-9) + 3.0 * np.log2(centers / 200.0)
        # Rango medido en canciones reales: ~-50 dB (silencio útil) a ~-10 dB (picos).
        return np.clip((db + 50.0) / 40.0, 0.0, 1.0) ** 1.5

    # ── Internos ───────────────────────────────────────────────────────────
    def _kill(self) -> None:
        if self._eq_timer is not None:
            self._eq_timer.cancel()
            self._eq_timer = None
        for pipe in (self._pipe, self._pending, self._fading):
            if pipe is not None:
                pipe.close()
        self._pipe = self._pending = self._fading = None

    def _start(self, start: float) -> None:
        self._kill()
        self._frames_played = int(start * SAMPLE_RATE)
        self.finished = False
        self.buffering = True
        self._pipe = self._spawn(self._frames_played)

    def _swap_filter(self) -> None:
        """Arranca un ffmpeg con el EQ nuevo en la posición actual; el callback hace el relevo."""
        with self._lock:
            self._eq_timer = None
            pipe = self._pipe
            if pipe is None or self._source is None or pipe.af == self._af:
                return
            if self._pending is not None:
                self._pending.close()
                self._pending = None
            if pipe.eof and pipe.buf.frames == 0:
                return  # la canción ya terminó
            self._pending = self._spawn(self._frames_played)

    def _spawn(self, start_frame: int) -> _Pipeline:
        start = start_frame / SAMPLE_RATE
        # -ss sobre una entrada por pipe decodifica y descarta hasta la posición;
        # con opus eso es mucho más rápido que tiempo real (~0.1 s por minuto).
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
        if start > 0:
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-i", "pipe:0", "-vn"]
        if self._af:
            cmd += ["-af", self._af]
        cmd += ["-f", "f32le", "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE), "pipe:1"]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        source = self._source
        assert source is not None
        pipe = _Pipeline(proc, PCMBuffer(self._buffer_frames), start_frame, self._af)
        threading.Thread(target=self._feeder, args=(proc, source), daemon=True).start()
        threading.Thread(target=self._reader, args=(pipe, source), daemon=True).start()
        return pipe

    @staticmethod
    def _feeder(proc: subprocess.Popen, source: AudioDownload) -> None:
        """Pasa los bytes descargados a ffmpeg a medida que llegan."""
        assert proc.stdin is not None
        offset = 0
        try:
            while True:
                chunk = source.read(offset, 64 * 1024)
                if not chunk or proc.poll() is not None:  # fin, error o ffmpeg ya cerrado
                    break
                proc.stdin.write(chunk)
                offset += len(chunk)
        except (BrokenPipeError, OSError, ValueError):
            pass  # ffmpeg terminó (seek, cambio de canción)
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    @staticmethod
    def _reader(pipe: _Pipeline, source: AudioDownload) -> None:
        proc = pipe.proc
        assert proc.stdout is not None and proc.stderr is not None
        read_bytes = 4096 * FRAME_BYTES
        while True:
            data = proc.stdout.read(read_bytes)
            if not data:
                break
            usable = len(data) - len(data) % FRAME_BYTES
            chunk = np.frombuffer(data[:usable], dtype=np.float32).reshape(-1, CHANNELS)
            if not pipe.buf.put(chunk):
                # Cola cerrada (seek, stop o relevo de EQ): ffmpeg ya no hace falta.
                try:
                    proc.kill()
                except OSError:
                    pass
                break
        code = proc.wait()
        if source.error:
            pipe.error = source.error
        elif code not in (0, -9):
            err = proc.stderr.read().decode(errors="replace").strip()
            pipe.error = err.splitlines()[-1] if err else f"ffmpeg salió con código {code}"
        pipe.eof = True

    def _try_swap(self, frames: int) -> None:
        """Relevo del pipeline con el EQ nuevo, alineado a la muestra con lo que suena."""
        # Nunca bloquear el hilo de audio: si el hilo de UI tiene el lock, se reintenta luego.
        if not self._lock.acquire(blocking=False):
            return
        try:
            pend = self._pending
            if pend is None:
                return
            behind = self._frames_played - pend.start_frame - pend.dropped
            if behind > 0:
                pend.dropped += pend.buf.discard(behind)
                behind = self._frames_played - pend.start_frame - pend.dropped
            if behind <= 0 and pend.buf.frames >= XFADE_FRAMES + frames:
                if self._fading is not None:
                    self._fading.buf.close()
                self._fading, self._fade_pos = self._pipe, 0
                self._pipe, self._pending = pend, None
            elif pend.eof:
                # Llegó al final sin alcanzar la posición (canción terminando): se descarta.
                pend.buf.close()
                self._pending = None
        finally:
            self._lock.release()

    def _crossfade(self, fading: _Pipeline, data: np.ndarray) -> np.ndarray:
        n = len(data)
        old = fading.buf.get(n)
        ramp = np.minimum((self._fade_pos + np.arange(1, n + 1, dtype=np.float32)) / XFADE_FRAMES, 1.0)
        out = data * ramp[:, None]
        m = len(old)
        out[:m] += old * (1.0 - ramp[:m, None])
        self._fade_pos += n
        if self._fade_pos >= XFADE_FRAMES:
            fading.buf.close()  # su lector mata ese ffmpeg
            self._fading = None
        return out

    def _callback(self, outdata: np.ndarray, frames: int, _time, status) -> None:
        if status.output_underflow:
            self.underruns += 1
        if self._pipe is None or self.paused:
            outdata.fill(0)
            self._scope *= 0.85  # decaimiento suave del visualizador en pausa
            return
        if self._pending is not None:
            self._try_swap(frames)
        pipe = self._pipe
        if pipe is None:
            outdata.fill(0)
            return
        buf = pipe.buf
        data = buf.get(frames)
        n = len(data)
        fading = self._fading
        if fading is not None and n:
            data = self._crossfade(fading, data)
        bal = self.balance
        gains = np.array([min(1.0, 1.0 - bal), min(1.0, 1.0 + bal)], dtype=np.float32)
        outdata[:n] = data * (gains * self.volume)
        outdata[n:] = 0
        self._frames_played += n
        if n:
            # Swap atómico: el hilo de UI nunca ve un buffer a medio escribir.
            self._scope = np.concatenate((self._scope[n:], data.mean(axis=1)))[-SCOPE_FRAMES:]
        self.buffering = n == 0 and not pipe.eof
        if n < frames and not pipe.eof:
            self.starved += 1
        if n < frames and pipe.eof and buf.frames == 0:
            self.finished = True
