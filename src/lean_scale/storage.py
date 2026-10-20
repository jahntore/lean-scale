"""Private XDG paths and atomic JSON persistence."""

import json
import os
import tempfile
from pathlib import Path


def config_path() -> Path:
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "lean-scale/config.json"
    )


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "lean-scale"


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    path = Path(base) / "lean-scale" if base else Path(f"/tmp/lean-scale-{os.getuid()}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    stat = path.lstat()
    if path.is_symlink() or stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise RuntimeError(f"Unsafe runtime directory: {path}; must be owned by you with mode 0700")
    return path


def recovery_path() -> Path:
    return data_dir() / "recovery.json"


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
            name = f.name
            json.dump(value, f, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def load_json(path: Path):
    with path.open() as f:
        return json.load(f)
