import pytest

from lean_scale.vision import eye_spacing

# Bounding box, two eyes, nose, mouth corners, confidence.
FACE = [100, 80, 180, 210, 140, 140, 220, 140, 180, 180, 150, 220, 210, 220, 0.99]


def test_eye_distance():
    assert eye_spacing([FACE], 640, 480) == pytest.approx(0.125)


def test_no_face():
    assert eye_spacing(None, 640, 480) is None
    assert eye_spacing([], 640, 480) is None


def test_multiple_faces_are_ambiguous():
    assert eye_spacing([FACE, FACE], 640, 480) is None


def test_yaw_is_rejected():
    turned = FACE.copy()
    turned[8] = 217
    assert eye_spacing([turned], 640, 480) is None


def test_clipped_face_rejected():
    clipped = FACE.copy()
    clipped[0] = -2
    assert eye_spacing([clipped], 640, 480) is None


def test_tilt_uses_euclidean_distance():
    tilted = FACE.copy()
    tilted[7] = 160
    assert eye_spacing([tilted], 640, 480) == pytest.approx((80**2 + 20**2) ** 0.5 / 640)
