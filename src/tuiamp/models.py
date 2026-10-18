from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


def parse_duration(value: Any) -> int:
    """'3:45' / '1:02:03' / 225 → segundos."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    parts = [p for p in str(value).split(":") if p.isdigit()]
    total = 0
    for p in parts:
        total = total * 60 + int(p)
    return total


def format_time(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def hires_thumbnail(url: str, size: int = 544) -> str:
    """Las miniaturas de googleusercontent aceptan el tamaño en el sufijo de la URL."""
    if "googleusercontent.com" in url or "ggpht.com" in url:
        return re.sub(r"=w\d+-h\d+.*$", f"=w{size}-h{size}-l90-rj", url)
    return url


@dataclass
class Track:
    video_id: str
    title: str
    artists: list[str] = field(default_factory=list)
    album: str = ""
    duration: int = 0
    thumbnail: str = ""

    @property
    def artist(self) -> str:
        return ", ".join(self.artists) or "Desconocido"

    @property
    def length(self) -> str:
        return format_time(self.duration) if self.duration else "--:--"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Track:
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})

    @classmethod
    def from_ytm(cls, item: dict[str, Any], album: dict[str, Any] | None = None) -> Track | None:
        video_id = item.get("videoId")
        if not video_id:
            return None
        thumbs = item.get("thumbnails") or item.get("thumbnail") or []
        if not thumbs and album:
            thumbs = album.get("thumbnails") or []
        thumb = thumbs[-1]["url"] if thumbs else ""
        album_info = item.get("album")
        album_name = album_info.get("name", "") if isinstance(album_info, dict) else ""
        if not album_name and album:
            album_name = album.get("title", "")
        duration = item.get("duration_seconds") or item.get("duration") or item.get("length")
        return cls(
            video_id=video_id,
            title=item.get("title") or "Sin título",
            artists=[a["name"] for a in item.get("artists") or [] if a.get("name")],
            album=album_name,
            duration=parse_duration(duration),
            thumbnail=hires_thumbnail(thumb) if thumb else "",
        )
