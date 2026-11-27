"""In-memory cache of rendered preview PNGs, bounded by total bytes (not by entry count).

Previews are never written to disk. A failed render is remembered as b"" so a broken file is
not rendered again on every request. Thread safe: preview requests run on the server's thread pool.
"""
from __future__ import annotations

import threading
from collections import OrderedDict


class PreviewCache:
    def __init__(self, max_bytes: int, max_entries: int = 4096):
        self.max_bytes = max(0, int(max_bytes))
        self.max_entries = max_entries
        self._d: OrderedDict = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key) -> bytes | None:
        """The cached PNG, b"" for a remembered failure, or None when not cached."""
        with self._lock:
            v = self._d.get(key)
            if v is not None:
                self._d.move_to_end(key)
            return v

    def put(self, key, value: bytes) -> None:
        if len(value) > self.max_bytes:
            return
        with self._lock:
            old = self._d.pop(key, None)
            if old is not None:
                self._bytes -= len(old)
            self._d[key] = value
            self._bytes += len(value)
            while self._d and (self._bytes > self.max_bytes or len(self._d) > self.max_entries):
                _, gone = self._d.popitem(last=False)
                self._bytes -= len(gone)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()
            self._bytes = 0

    @property
    def size_bytes(self) -> int:
        return self._bytes

    def __len__(self) -> int:
        return len(self._d)
