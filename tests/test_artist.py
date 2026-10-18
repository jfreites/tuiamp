"""Prueba headless de la búsqueda por artista, con un cliente falso (sin red ni audio)."""

from __future__ import annotations

from test_equalizer import SIZE, FakeClient, reset_settings, run, snapshot  # fija XDG_* antes que tuiamp

from tuiamp.api import SearchItem
from tuiamp.app import TuiampApp
from tuiamp.models import Track

SONGS = [Track(f"v{i}", f"Canción {i}", ["La Banda"], "Disco", 180 + i) for i in range(12)]
RELEASES = [
    SearchItem("album", "Primer disco", "Album · 2001", "MPREb_uno"),
    SearchItem("album", "Un single", "Single · 2020", "MPREb_dos"),
]
ALBUM = [
    Track("a1", "Pista 1", ["La Banda"], "Primer disco", 200),
    Track("a2", "Pista 2", ["La Banda"], "Primer disco", 210),
]


class FakeArtistClient(FakeClient):
    def __init__(self) -> None:
        self.searches: list[tuple[str, str]] = []

    def search(self, query: str, filter: str = "songs", limit: int = 40) -> list[SearchItem]:
        self.searches.append((query, filter))
        return [SearchItem("artist", "La Banda", "1M suscriptores", "UCbanda")]

    def artist(self, channel_id: str):
        assert channel_id == "UCbanda"
        return "La Banda", list(SONGS), list(RELEASES)

    def playlist_tracks(self, playlist_id: str, limit: int | None = 300) -> list[Track]:
        assert playlist_id == "MPREb_uno"
        return list(ALBUM)

    def lyrics(self, video_id: str):
        return None


def test_artist_search_and_play() -> None:
    reset_settings()

    async def body() -> None:
        client = FakeArtistClient()
        app = TuiampApp(client)
        async with app.run_test(size=SIZE) as pilot:
            played: list[str] = []
            app.resolve_and_play = lambda track, token, refresh=False: played.append(track.video_id)
            app.load_cover = lambda track, token: None

            app.query_one("#search-filter").value = "artists"
            await pilot.pause()
            app.query_one("#search-input").value = "la banda"
            app.query_one("#search-input").focus()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert client.searches[-1] == ("la banda", "artists")
            table = app.query_one("#search-table")
            assert [i.kind for i in table.items] == ["artist"]

            # Enter sobre el artista: sus canciones y, debajo, su discografía.
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(table.items) == len(SONGS) + len(RELEASES)
            assert table.is_collection
            snapshot(app, "artist")

            # Enter en la tercera canción: suena ella y la cola es toda la lista del artista.
            table.move_cursor(row=2)
            await pilot.press("enter")
            await pilot.pause()
            assert [t.video_id for t in app.queue.tracks] == [t.video_id for t in SONGS]
            assert app.queue.current.video_id == "v2" and played == ["v2"]

            # Enter en un disco: se abre y se reproduce entero.
            table.move_cursor(row=len(SONGS))
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert [t.video_id for t in app.queue.tracks] == ["a1", "a2"]

    run(body())
