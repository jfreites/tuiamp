"""Pruebas headless del ecualizador (ventana, presets, ON/AUTO y persistencia).

    TUIAMP_TEST_HOME=/ruta/temporal uv run --with pytest pytest tests

Los ajustes van a TUIAMP_TEST_HOME (o a un directorio temporal), nunca a ~/.config,
y el volumen se pone a 0 para que no suene nada.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

HOME = Path(os.environ.get("TUIAMP_TEST_HOME") or tempfile.mkdtemp(prefix="tuiamp-test-"))
os.environ["XDG_CONFIG_HOME"] = str(HOME / "config")
os.environ["XDG_CACHE_HOME"] = str(HOME / "cache")

from tuiamp.app import TuiampApp  # noqa: E402  (después de fijar XDG_*)
from tuiamp.audio import EQ_BANDS, eq_filter  # noqa: E402
from tuiamp.config import SETTINGS_FILE, Settings  # noqa: E402
from tuiamp.equalizer import EQ_PRESETS, EQSlider  # noqa: E402
from tuiamp.models import Track  # noqa: E402
from tuiamp.screens import OptionPicker  # noqa: E402

SIZE = (170, 45)
SNAPSHOTS = HOME / "snapshots"


class FakeClient:
    authenticated = False

    def library_playlists(self):
        return []


def reset_settings(**overrides) -> None:
    SETTINGS_FILE.unlink(missing_ok=True)
    settings = Settings.load()
    settings.volume = 0.0
    for key, value in overrides.items():
        setattr(settings, key, value)
    settings.save()


def saved() -> dict:
    return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))


def run(coro) -> None:
    asyncio.run(coro)


def snapshot(app: TuiampApp, name: str) -> None:
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    app.save_screenshot(filename=f"{name}.svg", path=str(SNAPSHOTS))


def test_eq_filter_chain() -> None:
    assert eq_filter(0, [0] * 10) is None
    af = eq_filter(3, [6, 0, 0, 0, 0, 0, 0, 0, 0, -12])
    assert af == "volume=+3.0dB,equalizer=f=60:t=o:w=1:g=+6.0,equalizer=f=16000:t=o:w=1:g=-12.0"
    assert len(EQ_BANDS) == 10
    for preamp, bands in EQ_PRESETS.values():
        assert len(bands) == 10 and all(-12 <= b <= 12 for b in [preamp, *bands])


def test_toggle_window() -> None:
    reset_settings()

    async def body() -> None:
        app = TuiampApp(FakeClient())
        async with app.run_test(size=SIZE) as pilot:
            window = app.query_one("#eq-window")
            assert not window.display  # oculta por defecto
            await pilot.press("escape", "e")
            await pilot.pause()
            assert window.display and app.query_one("#btn-eq").has_class("-on")
            assert saved()["show_eq"] is True
            snapshot(app, "eq-visible")
            await pilot.click("#btn-eq")
            await pilot.pause()
            assert not window.display and not app.query_one("#btn-eq").has_class("-on")
            assert saved()["show_eq"] is False

    run(body())


def test_preset_and_persistence() -> None:
    reset_settings(show_eq=True)

    async def body() -> None:
        app = TuiampApp(FakeClient())
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("escape", "E")
            await pilot.pause()
            assert isinstance(app.screen, OptionPicker)
            options = app.screen.query_one("OptionList")
            options.highlighted = list(EQ_PRESETS).index("Rock")
            await pilot.press("enter")
            await pilot.pause()
            preamp, bands = EQ_PRESETS["Rock"]
            assert app.query_one("#eq-0", EQSlider).value == bands[0]
            assert app.query_one("#eq-pre", EQSlider).value == preamp
            assert app.engine.eq_filter == eq_filter(preamp, bands)
            assert "Rock" in str(app.query_one("#eq-readout").render())
            snapshot(app, "eq-rock")

            # ON apaga el filtro sin perder las bandas.
            await pilot.click("#btn-eq-on")
            await pilot.pause()
            assert app.engine.eq_filter is None and not app.settings.eq_on
            await pilot.click("#btn-eq-on")
            await pilot.pause()
            assert app.engine.eq_filter == eq_filter(preamp, bands)

            # Clic arriba del todo en la banda de 1 kHz → +12 dB.
            await pilot.click("#eq-4", offset=(1, 0))
            await pilot.pause()
            assert app.settings.eq_bands[4] == 12.0
            assert app.settings.eq_preset == ""

        data = saved()
        assert data["eq_preset"] == "" and data["eq_bands"][4] == 12.0
        assert data["eq_bands"][0] == bands[0] and data["eq_preamp"] == preamp

        # Un arranque nuevo recupera el EQ: sliders y filtro de ffmpeg.
        app2 = TuiampApp(FakeClient())
        async with app2.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert app2.query_one("#eq-window").display
            assert app2.query_one("#eq-4", EQSlider).value == 12.0
            assert app2.query_one("#eq-0", EQSlider).value == bands[0]
            expected = list(bands)
            expected[4] = 12.0
            assert app2.engine.eq_filter == eq_filter(preamp, expected)

    run(body())


def test_auto_remembers_per_track() -> None:
    reset_settings(show_eq=True)

    async def body() -> None:
        app = TuiampApp(FakeClient())
        async with app.run_test(size=SIZE) as pilot:
            a, b = Track("aaa", "A"), Track("bbb", "B")
            app.queue.set([a, b], 0)
            await pilot.click("#btn-eq-auto")
            app.apply_eq_preset("Pop")
            await pilot.pause()
            assert app.settings.eq_per_track["aaa"][1:] == list(EQ_PRESETS["Pop"][1])
            app.queue.jump(1)
            app.apply_eq_preset("Classical")
            app.queue.jump(0)
            app._load_track_eq(a)  # lo que hace play_current con AUTO activo
            assert app.query_one("#eq-2", EQSlider).value == EQ_PRESETS["Pop"][1][2]
        assert set(saved()["eq_per_track"]) == {"aaa", "bbb"}

    run(body())


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("capturas en", SNAPSHOTS)
