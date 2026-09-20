"""Cross-process byte reservations; the journal never contains user content."""
from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import sqlite3
import uuid


def process_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if os.name == 'nt':
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        api.OpenProcess.restype = ctypes.c_void_p
        api.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Access denied is not proof of death.
        try:
            status = ctypes.c_ulong()
            return not api.GetExitCodeProcess(handle, ctypes.byref(status)) or status.value == 259
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def journal(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / 'upload-budget.sqlite3', timeout=10)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS reservations (token TEXT PRIMARY KEY, pid INTEGER, bytes INTEGER)')
        db.execute('BEGIN IMMEDIATE')
        for (pid,) in db.execute('SELECT DISTINCT pid FROM reservations').fetchall():
            if not process_alive(pid):
                db.execute('DELETE FROM reservations WHERE pid=?', (pid,))
        yield db
        db.commit()
    finally:
        db.close()


class ByteReservation:
    def __init__(self, root):
        self.root, self.token = Path(root), uuid.uuid4().hex
        self.released = False

    def reserve(self, amount, limit):
        if self.released:
            raise RuntimeError('Reservation already released')
        with journal(self.root) as db:
            active = db.execute('SELECT COALESCE(SUM(bytes),0) FROM reservations').fetchone()[0]
            if active + amount > limit:
                return False
            db.execute('INSERT INTO reservations VALUES (?,?,?) ON CONFLICT(token) DO UPDATE SET bytes=bytes+excluded.bytes', (self.token, os.getpid(), amount))
        return True

    def release(self):
        if not self.released:
            with journal(self.root) as db:
                db.execute('DELETE FROM reservations WHERE token=?', (self.token,))
            self.released = True


def reserved_bytes(root):
    with journal(root) as db:
        return db.execute('SELECT COALESCE(SUM(bytes),0) FROM reservations').fetchone()[0]
