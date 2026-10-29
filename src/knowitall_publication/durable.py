"""Local POSIX persistence primitives; no multi-host locking guarantee."""
import fcntl
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

_LOCKS = {}
_GUARD = threading.Lock()


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_directory(path: Path) -> None:
    if not path.exists():
        durable_directory(path.parent)
        path.mkdir(exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("durable directory must be a real directory")
    # An existing directory may be a mkdir left by interrupted initialization.
    # Persist its parent entry on reopening as well as on first creation.
    fsync_directory(path.parent)


def atomic_write(path: Path, data: bytes) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def locked(root: Path):
    """Reentrant across store instances in one thread, exclusive across processes."""
    key = str(root.resolve())
    with _GUARD:
        lock, state = _LOCKS.setdefault(key, (threading.RLock(), threading.local()))
    with lock:
        depth = getattr(state, "depth", 0)
        if depth == 0:
            state.file = (root / ".lock").open("a+b")
            fcntl.flock(state.file.fileno(), fcntl.LOCK_EX)
        state.depth = depth + 1
        try:
            yield
        finally:
            state.depth -= 1
            if state.depth == 0:
                fcntl.flock(state.file.fileno(), fcntl.LOCK_UN)
                state.file.close()
