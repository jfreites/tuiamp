"""Acceso a YouTube Music (ytmusicapi) y resolución de streams (yt-dlp)."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import yt_dlp
from ytmusicapi import YTMusic

from .config import AUTH_FILE
from .models import Track

SEARCH_FILTERS = ("songs", "albums", "artists", "playlists", "videos")


@dataclass
class SearchItem:
    kind: str  # song | album | playlist | artist
    title: str
    subtitle: str
    browse_id: str = ""
    track: Track | None = None


@dataclass
class Stream:
    url: str
    headers: dict[str, str]
    expires: float
    kbps: int = 0
    khz: int = 0
    channels: int = 2


@dataclass
class PlaylistRef:
    title: str
    playlist_id: str
    count: str = ""


def extract_playlist_id(text: str) -> str | None:
    """Acepta URLs de playlist/álbum o IDs pegados directamente en la búsqueda."""
    text = text.strip()
    if text.startswith("http"):
        query = parse_qs(urlparse(text).query)
        if "list" in query:
            return query["list"][0]
        match = re.search(r"/browse/((?:VL|MPRE)[\w-]+)", text)
        return match.group(1) if match else None
    if re.fullmatch(r"(PL|OLAK5uy_|VL|RD|LM|MPREb_)[\w-]*", text):
        return text
    return None


class YTMClient:
    def __init__(self) -> None:
        self.authenticated = AUTH_FILE.exists()
        self.yt = YTMusic(str(AUTH_FILE)) if self.authenticated else YTMusic()
        self._streams: dict[str, Stream] = {}
        self._stream_lock = threading.Lock()

    # ── Búsqueda y navegación ──────────────────────────────────────────────
    def search(self, query: str, filter: str = "songs", limit: int = 40) -> list[SearchItem]:
        results = self.yt.search(query, filter=filter, limit=limit)
        items: list[SearchItem] = []
        for r in results:
            kind = r.get("resultType")
            artists = ", ".join(a["name"] for a in r.get("artists") or [] if a.get("name"))
            if kind in ("song", "video"):
                track = Track.from_ytm(r)
                if track:
                    items.append(SearchItem("song", track.title, track.artist, track=track))
            elif kind == "album":
                sub = " · ".join(x for x in (artists, r.get("type"), str(r.get("year") or "")) if x)
                items.append(SearchItem("album", r.get("title", ""), sub, r.get("browseId", "")))
            elif kind == "playlist":
                sub = " · ".join(x for x in (r.get("author"), r.get("itemCount")) if x)
                items.append(SearchItem("playlist", r.get("title", ""), str(sub), r.get("browseId", "")))
            elif kind == "artist" and r.get("browseId"):
                sub = f"{r['subscribers']} suscriptores" if r.get("subscribers") else ""
                items.append(SearchItem("artist", r.get("artist", ""), sub, r["browseId"]))
        return items

    def artist(self, channel_id: str) -> tuple[str, list[Track], list[SearchItem]]:
        """Nombre, todas sus canciones y su discografía (álbumes y luego singles/EPs)."""
        data = self.yt.get_artist(channel_id)
        name = data.get("name", "")
        songs = data.get("songs") or {}
        tracks: list[Track] = []
        if songs.get("browseId"):
            try:  # la lista completa ("Ver todo"), no solo las 5 destacadas
                tracks = self.playlist_tracks(songs["browseId"])
            except Exception:
                tracks = []
        if not tracks:
            tracks = [t for t in (Track.from_ytm(r) for r in songs.get("results", [])) if t]
        releases: list[SearchItem] = []
        seen: set[str] = set()
        for key, label in (("albums", "Álbum"), ("singles", "Single")):
            section = data.get(key) or {}
            results = section.get("results", [])
            if section.get("browseId") and section.get("params"):
                try:
                    results = self.yt.get_artist_albums(section["browseId"], section["params"])
                except Exception:
                    pass
            for r in results:
                browse_id = r.get("browseId")
                if not browse_id or browse_id in seen:
                    continue
                seen.add(browse_id)
                sub = " · ".join(x for x in (r.get("type") or label, str(r.get("year") or "")) if x)
                releases.append(SearchItem("album", r.get("title", ""), sub, browse_id))
        return name, tracks, releases

    def album_tracks(self, browse_id: str) -> list[Track]:
        album = self.yt.get_album(browse_id)
        return [t for t in (Track.from_ytm(i, album) for i in album.get("tracks", [])) if t]

    def playlist_tracks(self, playlist_id: str, limit: int | None = 300) -> list[Track]:
        if playlist_id.startswith("MPRE"):
            return self.album_tracks(playlist_id)
        if playlist_id.startswith("RD"):
            data = self.yt.get_watch_playlist(playlistId=playlist_id, limit=limit or 50)
        else:
            data = self.yt.get_playlist(playlist_id, limit=limit)
        return [t for t in (Track.from_ytm(i) for i in data.get("tracks", [])) if t]

    def radio(self, video_id: str, limit: int = 40) -> list[Track]:
        data = self.yt.get_watch_playlist(videoId=video_id, limit=limit, radio=True)
        return [t for t in (Track.from_ytm(i) for i in data.get("tracks", [])) if t]

    def library_playlists(self) -> list[PlaylistRef]:
        if not self.authenticated:
            return []
        refs = [PlaylistRef("Canciones que te gustan", "LM")]
        for p in self.yt.get_library_playlists(limit=100):
            if p.get("playlistId") and p["playlistId"] != "LM":
                refs.append(PlaylistRef(p.get("title", ""), p["playlistId"], str(p.get("count") or "")))
        return refs

    def lyrics(self, video_id: str) -> dict[str, Any] | None:
        browse_id = self.yt.get_watch_playlist(videoId=video_id, limit=1).get("lyrics")
        if not browse_id:
            return None
        return self.yt.get_lyrics(browse_id, timestamps=True)

    # ── Streams ────────────────────────────────────────────────────────────
    def stream(self, video_id: str, refresh: bool = False) -> Stream:
        with self._stream_lock:
            cached = self._streams.get(video_id)
            if cached and not refresh and cached.expires - time.time() > 300:
                return cached
        opts = {
            "format": "bestaudio[acodec=opus]/bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://music.youtube.com/watch?v={video_id}", download=False)
        url = info["url"]
        expire = parse_qs(urlparse(url).query).get("expire", [None])[0]
        stream = Stream(
            url=url,
            headers=dict(info.get("http_headers") or {}),
            expires=float(expire) if expire else time.time() + 3600,
            kbps=int(info.get("abr") or info.get("tbr") or 0),
            khz=int((info.get("asr") or 0) / 1000),
            channels=int(info.get("audio_channels") or 2),
        )
        with self._stream_lock:
            self._streams[video_id] = stream
        return stream
