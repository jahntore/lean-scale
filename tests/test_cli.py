from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lean_scale import cli, hypr
from lean_scale.core import Config
from lean_scale.storage import load_json


@pytest.fixture
def simulation(monkeypatch, tmp_path):
    config = Config(
        "HDMI-A-1", "0", 0.2, 0.14, 1.3333334, 1.6666667, fps=10, dwell=0.2, smoothing=0.05
    )
    state = {"scale": config.normal_scale}
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "read_config", lambda _: config)
    monkeypatch.setattr(cli, "require_lua", lambda: None)
    monkeypatch.setattr(hypr, "get_monitor", lambda _: dict(state))
    setter = Mock(side_effect=lambda _, value: state.update(scale=value))
    monkeypatch.setattr(hypr, "set_scale", setter)
    path = tmp_path / "recovery.json"
    monkeypatch.setattr(hypr, "recovery_path", lambda: path)
    monkeypatch.setattr(cli, "recovery_path", lambda: path)

    clock = [0.0]
    monkeypatch.setattr(cli.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        cli.time, "sleep", lambda duration: clock.__setitem__(0, clock[0] + duration)
    )
    cameras = []

    class FakeCamera:
        def __init__(self, *_):
            cameras.append(self)
            self.closed = False
            self.reads = 0

        def read(self):
            assert not self.closed
            self.reads += 1
            if state.get("fail_camera") and self.reads >= 6:
                raise RuntimeError("Camera unplugged")
            return 0.14

        def close(self):
            self.closed = True

    class FakeServer:
        def __enter__(self):
            self.polls = 0
            return self

        def __exit__(self, *_):
            pass

        def poll(self, handler):
            self.polls += 1
            action = state.get("actions", {}).get(self.polls)
            if action:
                state["last_response"] = handler(action)
            if self.polls >= 15:
                handler("stop")

    monkeypatch.setattr(cli, "Camera", FakeCamera)
    monkeypatch.setattr(cli, "Server", FakeServer)
    args = SimpleNamespace(config=tmp_path / "config.json", dry_run=False)
    return args, state, setter, cameras, config


def test_run_stops_and_restores(simulation):
    args, state, setter, cameras, config = simulation
    cli.run(args)
    assert setter.call_count == 2
    assert setter.call_args_list[0].args[1] == config.leaned_scale
    assert state["scale"] == config.normal_scale
    assert len(cameras) == 1 and cameras[0].closed


def test_dry_run_only_logs(simulation):
    args, state, setter, cameras, config = simulation
    args.dry_run = True
    cli.run(args)
    setter.assert_not_called()
    assert state["scale"] == config.normal_scale
    assert cameras[0].closed


def test_pause_releases_camera_and_resume_reopens(simulation):
    args, state, setter, cameras, config = simulation
    state["actions"] = {7: "pause", 8: "status", 9: "resume"}
    cli.run(args)
    assert len(cameras) == 2 and all(camera.closed for camera in cameras)
    assert setter.call_count == 4
    assert state["scale"] == config.normal_scale


def test_camera_error_restores_scale(simulation):
    args, state, setter, cameras, config = simulation
    state["fail_camera"] = True
    with pytest.raises(RuntimeError, match="unplugged"):
        cli.run(args)
    assert setter.call_count == 2
    assert state["scale"] == config.normal_scale
    assert cameras[0].closed


def test_scale_mismatch_fails_before_opening_camera(simulation):
    args, state, setter, cameras, _ = simulation
    state["scale"] = 2
    with pytest.raises(RuntimeError, match="differs from calibration"):
        cli.run(args)
    setter.assert_not_called()
    assert not cameras


def test_calibration_saves_without_changing_scale(simulation, monkeypatch):
    args, _state, setter, cameras, config = simulation
    args.monitor, args.camera, args.lean_scale = "HDMI-A-1", "0", None
    monkeypatch.setattr(
        cli,
        "get_monitor",
        lambda _: {
            "name": "HDMI-A-1",
            "scale": config.normal_scale,
            "width": 5120,
            "height": 1440,
        },
    )
    readings = iter([0.2, 0.14])
    monkeypatch.setattr(cli, "sample", lambda *_: next(readings))
    cli.calibrate(args)
    result = Config(**load_json(args.config))
    assert result.normal_eye == 0.2
    assert result.leaned_scale == pytest.approx(5 / 3)
    assert cameras[0].closed
    setter.assert_not_called()


def test_invalid_config_never_opens_camera(simulation, monkeypatch):
    args, _, setter, cameras, config = simulation
    monkeypatch.setattr(cli, "read_config", lambda _: replace(config, normal_scale=2))
    with pytest.raises(ValueError):
        cli.run(args)
    assert not cameras
    setter.assert_not_called()
