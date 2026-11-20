"""A simple client-side rate limiter.

Open-Meteo doesn't need this for a one-off script, but the moment fetches are
run concurrently (see service.py) nothing stops every worker thread from
hitting the API in the same instant. Singular's real problem is the same
shape at a much bigger scale: dozens of worker threads/processes pulling from
many ad networks, each with its own rate limit, where a burst gets you
429-ed (or temporarily blocked) instead of throttled gracefully. A small,
provider-side limiter that every call goes through keeps outbound traffic
smooth regardless of how much concurrency sits on top of it.
"""

import threading
import time
from collections import deque


class RateLimiter:
    """Sliding-window-log limiter: at most `requests_per_second` calls/second,
    averaged over a window.

    For rates >= 1/sec the window is 1 second wide (e.g. 5/sec -> up to 5
    calls per rolling second). For fractional rates (e.g. 0.5/sec) a 1-second
    window would let `len(calls) < 0.5` admit a call immediately and then
    never again within that same second - which is not "0.5/sec", it's
    "however many 1-call bursts fit". Instead the window widens so exactly
    one call slot exists per `1 / requests_per_second` seconds, which holds
    for both fractional and whole rates.

    Thread-safe so it can be shared across the worker pool in service.py.
    """

    def __init__(self, requests_per_second: float):
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._requests_per_second = requests_per_second
        self._capacity = max(1, int(requests_per_second))
        self._window_seconds = self._capacity / requests_per_second
        self._call_times: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a new call is allowed under the configured rate."""
        while True:
            with self._lock:
                now = time.monotonic()
                # Drop timestamps that have fallen outside the sliding window.
                while self._call_times and now - self._call_times[0] >= self._window_seconds:
                    self._call_times.popleft()

                if len(self._call_times) < self._capacity:
                    self._call_times.append(now)
                    return

                # Window is full: figure out how long until the oldest call
                # expires, release the lock, and sleep outside of it so other
                # threads aren't blocked while we wait.
                sleep_for = self._window_seconds - (now - self._call_times[0])

            if sleep_for > 0:
                time.sleep(sleep_for)
