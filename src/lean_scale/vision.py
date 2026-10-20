"""YuNet face/eye tracking. No video frames are saved or transmitted."""

import hashlib
import math
import urllib.request
from pathlib import Path

from .storage import data_dir

MODEL_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/"
    "47534e27c9851bb1128ccc0102f1145e27f23f98/"
    "models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"


def model_path() -> Path:
    return data_dir() / "face_detection_yunet_2023mar.onnx"


def verify_model(path: Path):
    if not path.exists():
        raise RuntimeError("Face model missing. Run `lean-scale setup` first.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
        raise RuntimeError("Face model checksum mismatch. Run `lean-scale setup` to replace it.")


def install_model():
    path = model_path()
    if path.exists():
        try:
            verify_model(path)
            return path
        except RuntimeError:
            pass
    with urllib.request.urlopen(MODEL_URL, timeout=30) as response:
        data = response.read(1_000_001)
    if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
        raise RuntimeError("Downloaded model failed checksum verification")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Only setup downloads anything. Runtime never needs network access.
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        f.write(data)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def eye_spacing(faces, width: int, height: int) -> float | None:
    if faces is None or len(faces) != 1:
        return None
    face = faces[0]
    x, y, w, h = map(float, face[:4])
    if w < 50 or h < 50 or x < 0 or y < 0 or x + w > width or y + h > height:
        return None
    # YuNet: bounding box, right eye, left eye, nose, mouth corners, score.
    ax, ay, bx, by, nx, ny = map(float, face[4:10])
    dx, dy = bx - ax, by - ay
    distance = math.hypot(dx, dy)
    if distance < 18:
        return None
    projection = ((nx - ax) * dx + (ny - ay) * dy) / distance**2
    # Reject substantial yaw, which would otherwise look like moving away.
    if not 0.25 <= projection <= 0.75:
        return None
    return distance / width


class Camera:
    def __init__(self, device: str, fps: float = 8):
        import cv2

        path = model_path()
        verify_model(path)
        self.cv2 = cv2
        self.detector = cv2.FaceDetectorYN.create(str(path), "", (640, 480), 0.85, 0.3, 5000)
        source = int(device) if device.isdecimal() else device
        if not isinstance(source, int) and not str(source).startswith("/dev/"):
            raise ValueError("Camera must be an index or local /dev/ device, not a URL or file")
        self.cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            self.cap.release()
            raise RuntimeError(
                f"Cannot open camera {device}; check device, permissions, or other apps"
            )
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.failures = 0

    def read(self) -> float | None:
        ok, frame = self.cap.read()
        if not ok:
            self.failures += 1
            if self.failures >= 10:
                raise RuntimeError("Camera stopped delivering frames; stopping and restoring scale")
            return None
        self.failures = 0
        height, width = frame.shape[:2]
        if width > 640:
            frame = self.cv2.resize(frame, (640, round(height * 640 / width)))
            height, width = frame.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(frame)
        return eye_spacing(faces, width, height)

    def close(self):
        self.cap.release()
