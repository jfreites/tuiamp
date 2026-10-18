"""Letras: primero YouTube Music (LyricFind), y LRCLIB como respaldo para letras sincronizadas."""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field

import httpx

from .api import YTMClient
from .models import Track

LRCLIB = "https://lrclib.net/api"
_LRC_LINE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


@dataclass
class Lyrics:
    lines: list[str]
    times: list[float] = field(default_factory=list)  # segundos, solo si synced
    source: str = ""

    @property
    def synced(self) -> bool:
        return bool(self.times)

    def index_at(self, position: float) -> int:
        """Índice de la línea activa para la posición dada (-1 antes de la primera)."""
        return bisect_right(self.times, position) - 1


def parse_lrc(text: str) -> Lyrics:
    entries: list[tuple[float, str]] = []
    for raw in text.splitlines():
        stamps = list(_LRC_LINE.finditer(raw))
        if not stamps:
            continue
        lyric = _LRC_LINE.sub("", raw).strip()
        for m in stamps:
            entries.append((int(m.group(1)) * 60 + float(m.group(2)), lyric))
    entries.sort(key=lambda e: e[0])
    return Lyrics([e[1] for e in entries], [e[0] for e in entries])


def _from_ytm(client: YTMClient, track: Track) -> Lyrics | None:
    data = client.lyrics(track.video_id)
    if not data or not data.get("lyrics"):
        return None
    source = (data.get("source") or "YouTube Music").replace("Source: ", "")
    if data.get("hasTimestamps"):
        lines = data["lyrics"]
        return Lyrics([l.text for l in lines], [l.start_time / 1000 for l in lines], source)
    return Lyrics(str(data["lyrics"]).splitlines(), source=source)


def _from_lrclib(track: Track) -> Lyrics | None:
    headers = {"User-Agent": "tuiamp/0.1"}
    artist = track.artists[0] if track.artists else ""
    title = re.sub(r"\s*[\(\[](feat|ft|with)\.?[^\)\]]*[\)\]]", "", track.title, flags=re.I)
    with httpx.Client(timeout=8, headers=headers) as http:
        params = {"track_name": title, "artist_name": artist}
        if track.album:
            params["album_name"] = track.album
        if track.duration:
            params["duration"] = str(track.duration)
        resp = http.get(f"{LRCLIB}/get", params=params)
        record = resp.json() if resp.status_code == 200 else None
        if not record or not (record.get("syncedLyrics") or record.get("plainLyrics")):
            resp = http.get(f"{LRCLIB}/search", params={"track_name": title, "artist_name": artist})
            candidates = resp.json() if resp.status_code == 200 else []
            candidates = [c for c in candidates if c.get("syncedLyrics") or c.get("plainLyrics")]
            if track.duration:
                candidates.sort(key=lambda c: abs((c.get("duration") or 0) - track.duration))
            record = candidates[0] if candidates else None
    if not record:
        return None
    if record.get("syncedLyrics"):
        lyrics = parse_lrc(record["syncedLyrics"])
        lyrics.source = "LRCLIB"
        return lyrics
    if record.get("plainLyrics"):
        return Lyrics(record["plainLyrics"].splitlines(), source="LRCLIB")
    return None


def fetch_lyrics(client: YTMClient, track: Track) -> Lyrics | None:
    """Prefiere letras sincronizadas de cualquier fuente; si no, texto plano."""
    plain: Lyrics | None = None
    for fetch in (lambda: _from_ytm(client, track), lambda: _from_lrclib(track)):
        try:
            result = fetch()
        except Exception:
            continue
        if result and result.synced:
            return result
        plain = plain or result
    return plain
