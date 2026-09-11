"""Bounded local summary-only transport. No controls, file imports or playback."""

import fcntl
import json
import os
import socket
import stat
import sys
import threading
import time
from pathlib import Path

MAX_FRAME = 10000


def _frame(client, limit=MAX_FRAME, timeout=2):
    deadline = time.monotonic() + timeout
    raw = bytearray()
    while b'\n' not in raw:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or len(raw) >= limit:
            raise ValueError('Invalid summary frame')
        client.settimeout(remaining)
        chunk = client.recv(min(4096, limit + 1 - len(raw)))
        if not chunk:
            raise ValueError('Invalid summary frame')
        raw.extend(chunk)
    if len(raw) > limit or not raw.endswith(b'\n'):
        raise ValueError('Invalid summary frame')
    try:
        return json.loads(raw)
    except RecursionError as error:
        raise ValueError('Invalid summary frame') from error


def submit(socket_path, token, payload):
    """The agent client needs no database access and receives no other tokens."""
    from .summary import summary_body
    summary_body(payload)
    if not isinstance(token, str) or len(token) > 100:
        raise ValueError('Invalid notification token')
    raw = (json.dumps({'token': token, 'summary': payload}, ensure_ascii=False) + '\n').encode()
    if len(raw) > MAX_FRAME:
        raise ValueError('Summary payload is too large')
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(3)
        client.connect(str(socket_path))
        client.sendall(raw)
        result = _frame(client, 1024, timeout=3)
    if result != {'staged': True}:
        raise ValueError('Summary rejected: check current turn and speech switches')
    return result


class SummaryBroker:
    """Owned by trusted MCP; at most four clients, short bounded reads."""
    def __init__(self, store, socket_path):
        self.store = store
        self.path = Path(socket_path).absolute()
        self.stop = threading.Event()
        self.slots = threading.BoundedSemaphore(4)
        self.lock_fd = None
        self.listener = None
        self.inode = None
        self.thread = None
        self.clients = set()
        self.workers = set()
        self.clients_lock = threading.Lock()

    def __enter__(self):
        try:
            if self.path != self.path.resolve() or len(os.fsencode(self.path)) > 103:
                raise ValueError('Summary socket needs a short, non-symlink absolute path')
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            parent = self.path.parent.stat()
            if parent.st_uid != os.getuid() or parent.st_mode & 0o022:
                raise ValueError('Summary socket directory must be private and owned by this user')
            self.lock_fd = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            info = os.fstat(self.lock_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise ValueError('Invalid summary listener lock')
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.path.exists() or self.path.is_symlink():
                info = self.path.lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                    raise ValueError('Refusing to overwrite summary socket path')
                self.path.unlink()  # Only stale owned sockets; the lock excludes a live owner.
            self.listener = socket.socket(socket.AF_UNIX)
            self.listener.bind(str(self.path))
            os.chmod(self.path, 0o600)
            self.inode = self.path.stat().st_ino
            self.listener.listen(4)
            self.listener.settimeout(0.2)
            self.thread = threading.Thread(target=self._listen, daemon=True)
            self.thread.start()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _listen(self):
        while not self.stop.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if not self.slots.acquire(blocking=False):
                client.close()
                continue
            worker = threading.Thread(target=self._receive, args=(client,), daemon=True)
            with self.clients_lock:
                self.clients.add(client)
                self.workers.add(worker)
            worker.start()

    def _receive(self, client):
        import sqlite3  # Trusted broker only; the sandboxed client never needs SQLite.
        result = {'staged': False}
        try:
            request = _frame(client)
            if (not isinstance(request, dict) or set(request) != {'token', 'summary'}
                    or not isinstance(request['token'], str) or len(request['token']) > 100):
                raise ValueError('Invalid submission')
            if not self.stop.is_set():
                self.store.stage_summary(request['token'], request['summary'],
                                         cancelled=self.stop.is_set, timeout=.5)
                result = {'staged': True}
        except (ValueError, TypeError, OSError, UnicodeError, sqlite3.Error):
            pass
        finally:
            try:
                client.sendall((json.dumps(result) + '\n').encode())
            except OSError:
                pass
            client.close()
            with self.clients_lock:
                self.clients.discard(client)
                self.workers.discard(threading.current_thread())
            self.slots.release()

    def __exit__(self, *exc):
        self.stop.set()
        if self.listener:
            self.listener.close()
        with self.clients_lock:
            for client in self.clients:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        if self.thread:
            self.thread.join(timeout=1)
        with self.clients_lock:
            workers = list(self.workers)
        for worker in workers:
            worker.join()  # Frame deadline / short SQLite timeout bound work before releasing the lease.
        if self.inode is not None:
            try:
                if self.path.lstat().st_ino == self.inode:
                    self.path.unlink()
            except FileNotFoundError:
                pass
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None


class SharedSummaryBroker:
    """One listener across trusted MCP processes; surviving peers take over.

    The lock selects a listener, not a security identity. All peers must use the
    same protected runtime, state and socket configuration. Each process owns
    only its own lease and never removes another live listener's socket.
    """
    def __init__(self, store, socket_path):
        self.store = store
        self.path = socket_path
        self.stop = threading.Event()
        self.leader = None
        self.thread = None

    def _acquire(self):
        try:
            self.leader = SummaryBroker(self.store, self.path).__enter__()
        except BlockingIOError:
            pass  # Another trusted MCP owns the listener; keep serving controls.

    def __enter__(self):
        self._acquire()  # Invalid/unsafe paths fail startup; only a busy lock is shared.
        self.thread = threading.Thread(target=self._supervise, daemon=True)
        self.thread.start()
        return self

    def _supervise(self):
        while not self.stop.wait(.2):
            if self.leader is None:
                try:
                    self._acquire()
                except (OSError, ValueError):
                    print('Attention: summary listener unavailable; check the protected socket directory.',
                          file=sys.stderr)
                    return

    def __exit__(self, *exc):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)
        if self.leader is not None:
            self.leader.__exit__(*exc)
            self.leader = None
