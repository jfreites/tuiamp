from __future__ import annotations

import random

from .models import Track

REPEAT_MODES = ("off", "all", "one")


class PlayQueue:
    def __init__(self) -> None:
        self.tracks: list[Track] = []
        self.index = -1
        self.shuffle = False
        self.repeat = "off"
        self._original: list[Track] = []

    @property
    def current(self) -> Track | None:
        return self.tracks[self.index] if 0 <= self.index < len(self.tracks) else None

    def set(self, tracks: list[Track], start: int = 0) -> None:
        self.tracks = list(tracks)
        self._original = list(tracks)
        self.index = start if tracks else -1
        if self.shuffle and tracks:
            self._shuffle_rest()

    def add(self, track: Track) -> None:
        self.tracks.append(track)
        self._original.append(track)
        if self.index < 0:
            self.index = 0

    def add_next(self, track: Track) -> None:
        self.tracks.insert(self.index + 1, track)
        self._original.append(track)
        if self.index < 0:
            self.index = 0

    def remove(self, i: int) -> None:
        if not 0 <= i < len(self.tracks):
            return
        track = self.tracks.pop(i)
        if track in self._original:
            self._original.remove(track)
        if i < self.index:
            self.index -= 1
        elif i == self.index and self.index >= len(self.tracks):
            self.index = len(self.tracks) - 1

    def move(self, i: int, delta: int) -> int:
        j = i + delta
        if not (0 <= i < len(self.tracks) and 0 <= j < len(self.tracks)):
            return i
        self.tracks[i], self.tracks[j] = self.tracks[j], self.tracks[i]
        if self.index == i:
            self.index = j
        elif self.index == j:
            self.index = i
        return j

    def jump(self, i: int) -> Track | None:
        if 0 <= i < len(self.tracks):
            self.index = i
        return self.current

    def next(self, auto: bool = False) -> Track | None:
        """`auto` = fin natural de la canción (respeta repeat one)."""
        if not self.tracks:
            return None
        if auto and self.repeat == "one":
            return self.current
        if self.index + 1 < len(self.tracks):
            self.index += 1
        elif self.repeat == "all":
            self.index = 0
        else:
            return None
        return self.current

    def previous(self) -> Track | None:
        if not self.tracks:
            return None
        if self.index > 0:
            self.index -= 1
        elif self.repeat == "all":
            self.index = len(self.tracks) - 1
        return self.current

    def peek_next(self) -> Track | None:
        if self.repeat == "one":
            return self.current
        if self.index + 1 < len(self.tracks):
            return self.tracks[self.index + 1]
        return self.tracks[0] if self.repeat == "all" and self.tracks else None

    def toggle_shuffle(self) -> bool:
        self.shuffle = not self.shuffle
        if self.shuffle:
            self._shuffle_rest()
        else:
            current = self.current
            self.tracks = list(self._original)
            self.index = self.tracks.index(current) if current in self.tracks else 0
        return self.shuffle

    def cycle_repeat(self) -> str:
        self.repeat = REPEAT_MODES[(REPEAT_MODES.index(self.repeat) + 1) % len(REPEAT_MODES)]
        return self.repeat

    def _shuffle_rest(self) -> None:
        current = self.current
        rest = [t for t in self.tracks if t is not current]
        random.shuffle(rest)
        self.tracks = ([current] if current else []) + rest
        self.index = 0 if current else -1
