"""Single-instance locking and private local control socket."""

import fcntl
import json
import socket
from contextlib import AbstractContextManager

from .storage import runtime_dir


class Lock(AbstractContextManager):
    def __enter__(self):
        self.file = (runtime_dir() / "daemon.lock").open("a+")
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.file.close()
            raise RuntimeError(
                "lean-scale is already running or calibrating; stop it first"
            ) from exc
        return self

    def __exit__(self, *args):
        self.file.close()


class Server(AbstractContextManager):
    def __enter__(self):
        self.path = runtime_dir() / "control.sock"
        self.path.unlink(missing_ok=True)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(self.path))
        self.socket.listen(4)
        self.socket.setblocking(False)
        return self

    def poll(self, handler):
        # Bound the work, so a flood of requests cannot starve camera processing.
        for _ in range(4):
            try:
                connection, _ = self.socket.accept()
            except BlockingIOError:
                return
            with connection:
                connection.settimeout(0.1)
                try:
                    command = connection.recv(128).decode("ascii").strip()
                    response = handler(command)
                    connection.sendall(json.dumps(response).encode() + b"\n")
                except (OSError, UnicodeError):
                    pass

    def __exit__(self, *args):
        self.socket.close()
        self.path.unlink(missing_ok=True)


def request(command: str):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(8)
        try:
            sock.connect(str(runtime_dir() / "control.sock"))
            sock.sendall(command.encode("ascii") + b"\n")
            response = bytearray()
            while b"\n" not in response and len(response) < 65536:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response.extend(chunk)
        except OSError as exc:
            raise RuntimeError("Cannot reach lean-scale; is `lean-scale run` running?") from exc
    return json.loads(response)
