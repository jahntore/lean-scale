from unittest.mock import Mock

import pytest

from lean_scale import hypr
from lean_scale.storage import load_json, save_json


@pytest.fixture
def fake(monkeypatch, tmp_path):
    state = {"scale": 1.3333334}
    monkeypatch.setattr(hypr, "get_monitor", lambda _: dict(state))
    setter = Mock(side_effect=lambda _, scale: state.update(scale=scale))
    monkeypatch.setattr(hypr, "set_scale", setter)
    path = tmp_path / "recovery.json"
    monkeypatch.setattr(hypr, "recovery_path", lambda: path)
    return state, setter, path


def test_dry_run_never_mutates(fake):
    state, setter, path = fake
    display = hypr.Display("HDMI-A-1", dry_run=True)
    display.apply(1.6)
    display.restore()
    setter.assert_not_called()
    assert state["scale"] == 1.3333334
    assert not path.exists()
    assert display.expected == display.original


def test_apply_and_restore(fake):
    state, setter, path = fake
    display = hypr.Display("HDMI-A-1")
    display.apply(1.6)
    assert load_json(path)["original_scale"] == 1.3333334
    assert state["scale"] == 1.6
    display.restore()
    assert state["scale"] == 1.3333334
    assert not path.exists()
    assert setter.call_count == 2


def test_external_change_not_overwritten(fake):
    state, setter, path = fake
    display = hypr.Display("HDMI-A-1")
    display.apply(1.6)
    state["scale"] = 2
    with pytest.raises(RuntimeError, match="externally"):
        display.apply(1.3333334)
    display.restore()
    assert state["scale"] == 2
    assert setter.call_count == 1
    assert not path.exists()


def test_crash_before_mutation_recovers(fake):
    _, setter, path = fake
    save_json(
        path,
        {
            "monitor": "HDMI-A-1",
            "original_scale": 1.3333334,
            "previous_scale": 1.3333334,
            "target_scale": 1.6,
        },
    )
    hypr.restore_saved()
    setter.assert_not_called()
    assert not path.exists()


def test_crash_after_mutation_recovers(fake):
    state, _, path = fake
    state["scale"] = 1.6
    save_json(
        path,
        {
            "monitor": "HDMI-A-1",
            "original_scale": 1.3333334,
            "previous_scale": 1.3333334,
            "target_scale": 1.6,
        },
    )
    hypr.restore_saved()
    assert state["scale"] == 1.3333334
    assert not path.exists()


def test_valid_scale_on_ultrawide():
    scale = hypr.closest_scale({"width": 5120, "height": 1440}, 1.3333334 * 1.25)
    assert scale == pytest.approx(5 / 3)
    assert 5120 / scale == pytest.approx(3072)
    assert 1440 / scale == pytest.approx(864)


def test_invalid_scale_rollback(fake):
    state, setter, path = fake

    def rejecting(_, scale):
        if scale == 1.6:
            state["scale"] = 1.5  # compositor substituted an unexpected value
            raise RuntimeError("Scale rejected")
        state["scale"] = scale

    setter.side_effect = rejecting
    display = hypr.Display("HDMI-A-1")
    with pytest.raises(RuntimeError, match="rejected"):
        display.apply(1.6)
    assert state["scale"] == display.original
    assert not path.exists()


def test_help_exit_one_is_supported(monkeypatch):
    import subprocess

    monkeypatch.setattr(
        hypr.subprocess,
        "run",
        lambda *_, **__: subprocess.CompletedProcess(
            ["hyprctl", "--help"],
            1,
            "commands:\n    eval <code>  Issue Lua\n    seterror   Set the error string",
            "",
        ),
    )
    hypr.require_lua()


def test_lua_scale_only():
    assert hypr.scale_lua("HDMI-A-1", 1.6) == 'hl.monitor({output="HDMI-A-1", scale=1.600000000})'


@pytest.mark.parametrize("name, scale", [('x"});os.execute("oops")', 1.6), ("eDP-1", float("nan"))])
def test_reject_lua_injection_and_nan(name, scale):
    with pytest.raises(ValueError):
        hypr.scale_lua(name, scale)
