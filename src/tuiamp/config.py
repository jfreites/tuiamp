"""Rutas, ajustes persistentes y playlists locales."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .models import Track

APP_NAME = "tuiamp"
LEGACY_NAME = "ytmusic-tui"  # nombre anterior del proyecto
_CONFIG_ROOT = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_DIR = _CONFIG_ROOT / APP_NAME
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / APP_NAME

# Conserva ajustes, playlists y login de cuando el proyecto se llamaba ytmusic-tui.
if not CONFIG_DIR.exists() and (_CONFIG_ROOT / LEGACY_NAME).is_dir():
    shutil.copytree(_CONFIG_ROOT / LEGACY_NAME, CONFIG_DIR)
AUTH_FILE = CONFIG_DIR / "browser.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
PLAYLISTS_FILE = CONFIG_DIR / "playlists.json"


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


EQ_BAND_COUNT = 10
EQ_LIMIT = 12.0


def _clamp_db(value: object) -> float:
    try:
        return round(min(max(float(value), -EQ_LIMIT), EQ_LIMIT), 1)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


@dataclass
class Settings:
    theme: str = "winamp-classic"
    volume: float = 0.8
    visualizer: str = "bars"
    show_lyrics: bool = True
    shuffle: bool = False
    repeat: str = "off"  # off | all | one
    balance: float = 0.0
    skin_v2: bool = False  # al pasar a Tuiamp se estrena el skin winamp-classic una vez
    show_eq: bool = False
    eq_on: bool = True
    eq_auto: bool = False  # cada canción recuerda su EQ, como el AUTO de Winamp
    eq_preamp: float = 0.0
    eq_bands: list[float] = field(default_factory=lambda: [0.0] * EQ_BAND_COUNT)
    eq_preset: str = "Flat"
    eq_per_track: dict[str, list[float]] = field(default_factory=dict)  # video_id → [preamp, *bandas]

    @classmethod
    def load(cls) -> Settings:
        data = _read_json(SETTINGS_FILE, {})
        if not isinstance(data, dict):
            data = {}
        known = {f.name for f in fields(cls)}
        settings = cls(**{k: v for k, v in data.items() if k in known})
        settings.eq_preamp = _clamp_db(settings.eq_preamp)
        bands = settings.eq_bands if isinstance(settings.eq_bands, list) else []
        bands = [_clamp_db(b) for b in bands[:EQ_BAND_COUNT]]
        settings.eq_bands = bands + [0.0] * (EQ_BAND_COUNT - len(bands))
        if not isinstance(settings.eq_per_track, dict):
            settings.eq_per_track = {}
        settings.eq_per_track = {
            k: [_clamp_db(x) for x in v]
            for k, v in settings.eq_per_track.items()
            if isinstance(v, list) and len(v) == EQ_BAND_COUNT + 1
        }
        if not settings.skin_v2:
            settings.theme, settings.skin_v2 = "winamp-classic", True
        return settings

    def save(self) -> None:
        _write_json(SETTINGS_FILE, asdict(self))


class LocalPlaylists:
    """Playlists guardadas en disco, independientes de la cuenta de YouTube Music."""

    def __init__(self) -> None:
        raw = _read_json(PLAYLISTS_FILE, {})
        self.data: dict[str, list[Track]] = {}
        if isinstance(raw, dict):
            for name, items in raw.items():
                self.data[name] = [Track.from_dict(t) for t in items if isinstance(t, dict)]

    def names(self) -> list[str]:
        return sorted(self.data, key=str.lower)

    def get(self, name: str) -> list[Track]:
        return list(self.data.get(name, []))

    def create(self, name: str, tracks: list[Track] | None = None) -> None:
        self.data[name] = list(tracks or [])
        self.save()

    def add(self, name: str, track: Track) -> bool:
        items = self.data.setdefault(name, [])
        if any(t.video_id == track.video_id for t in items):
            return False
        items.append(track)
        self.save()
        return True

    def remove(self, name: str, index: int) -> None:
        items = self.data.get(name)
        if items and 0 <= index < len(items):
            del items[index]
            self.save()

    def delete(self, name: str) -> None:
        if self.data.pop(name, None) is not None:
            self.save()

    def save(self) -> None:
        _write_json(PLAYLISTS_FILE, {k: [t.to_dict() for t in v] for k, v in self.data.items()})
