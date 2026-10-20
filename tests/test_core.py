import math
from dataclasses import replace

import pytest

from lean_scale.core import Config, Controller


@pytest.fixture
def config():
    return Config("HDMI-A-1", "0", 0.2, 0.14, 1.333333, 1.666667)


def feed(controller, value, start, duration):
    changes = []
    for i in range(round(duration * 10) + 1):
        result = controller.update(value, start + i / 10)
        if result:
            changes.append(result)
    return changes


def test_normal_is_quiet(config):
    assert feed(Controller(config), 0.2, 0, 20) == []


def test_dwell_required(config):
    controller = Controller(config)
    assert feed(controller, 0.14, 0, 1) == []
    assert feed(controller, 0.14, 1.1, 1) == ["leaned"]


def test_lean_then_return(config):
    controller = Controller(config)
    assert feed(controller, 0.14, 0, 3) == ["leaned"]
    assert feed(controller, 0.2, 3.1, 4) == ["normal"]


def test_hysteresis_holds_state(config):
    controller = Controller(config)
    assert feed(controller, 0.14, 0, 3) == ["leaned"]
    assert feed(controller, 0.17, 3.1, 10) == []
    assert controller.state == "leaned"


def test_missing_reading_breaks_dwell(config):
    controller = Controller(config)
    feed(controller, 0.14, 0, 1.5)
    assert controller.update(None, 1.6) is None
    assert feed(controller, 0.14, 1.7, 1.5) == []


def test_brief_loss_holds_scale(config):
    controller = Controller(config)
    feed(controller, 0.14, 0, 3)
    assert controller.update(None, 4) is None
    assert controller.state == "leaned"


def test_long_loss_returns_to_normal_once(config):
    controller = Controller(config)
    feed(controller, 0.14, 0, 3)
    assert controller.update(None, 8) == "normal"
    assert controller.update(None, 9) is None
    assert controller.smoothed is None


def test_no_face_at_start_is_quiet(config):
    assert feed(Controller(config), None, 0, 20) == []


def test_capture_gap_does_not_complete_dwell(config):
    controller = Controller(config)
    feed(controller, 0.14, 0, 1)
    assert controller.update(0.14, 10) is None
    assert controller.state == "normal"


def test_reset_forgets_old_posture(config):
    controller = Controller(config)
    feed(controller, 0.14, 0, 3)
    controller.reset()
    assert controller.state == "normal"
    assert controller.progress is None


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1, 0])
def test_invalid_measurements_never_trigger(config, bad):
    assert feed(Controller(config), bad, 0, 10) == []


@pytest.mark.parametrize(
    "change",
    [
        {"leaned_eye": 0.19},
        {"normal_eye": 0},
        {"leaned_eye": -1},
        {"normal_scale": math.nan},
        {"leaned_scale": 1},
        {"leaned_scale": 5},
        {"fps": 0},
        {"dwell": 0},
        {"hysteresis": 0.5},
        {"lost_timeout": 0},
        {"smoothing": -1},
        {"camera": ""},
        {"monitor": ""},
    ],
)
def test_config_rejects_invalid(config, change):
    with pytest.raises(ValueError):
        replace(config, **change)
