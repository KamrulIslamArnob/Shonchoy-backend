"""Bounded in-process protection for hosted advisor requests."""

import hashlib
import hmac
import secrets
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from threading import Lock


class AdvisorRateLimiter:
    def __init__(
        self, limit: int = 20, window: float = 60, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window
        self.clock = clock
        self.secret = secrets.token_bytes(32)
        self.entries: OrderedDict[bytes, deque[float]] = OrderedDict()
        self.lock = Lock()

    def allow(self, subject: str) -> bool:
        digest = hmac.new(self.secret, subject.encode("utf-8"), hashlib.sha256).digest()
        now = self.clock()
        with self.lock:
            queue = self.entries.setdefault(digest, deque())
            self.entries.move_to_end(digest)
            while queue and queue[0] <= now - self.window:
                queue.popleft()
            if len(queue) >= self.limit:
                return False
            queue.append(now)
            if len(self.entries) > 10_000:
                self.entries.popitem(last=False)
            return True
