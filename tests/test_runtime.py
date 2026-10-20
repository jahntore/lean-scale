import os
import threading
import time

import pytest

from lean_scale.runtime import Lock, Server, request
from lean_scale.storage import load_json, runtime_dir, save_json


@pytest.fixture(autouse=True)
def private_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))


def test_lock_excludes_other_instances():
    with Lock(), pytest.raises(RuntimeError, match="already running"), Lock():
        pass
    with Lock():
        pass


def test_control_socket():
    result = []
    with Lock(), Server() as server:
        thread = threading.Thread(target=lambda: result.append(request("status")))
        thread.start()
        deadline = time.monotonic() + 2
        while thread.is_alive() and time.monotonic() < deadline:
            server.poll(lambda command: {"command": command, "paused": True})
            time.sleep(0.01)
        thread.join(timeout=1)
    assert result == [{"command": "status", "paused": True}]


def test_runtime_directory_is_private():
    path = runtime_dir()
    assert path.stat().st_mode & 0o077 == 0
    os.chmod(path, 0o755)
    with pytest.raises(RuntimeError, match="Unsafe"):
        runtime_dir()


def test_json_atomic_and_private(tmp_path):
    path = tmp_path / "config.json"
    save_json(path, {"test": 1})
    save_json(path, {"test": 2})
    assert load_json(path) == {"test": 2}
    assert path.stat().st_mode & 0o077 == 0
