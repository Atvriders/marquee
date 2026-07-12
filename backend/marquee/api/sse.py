from __future__ import annotations

import queue


class Broadcaster:
    """Thread-safe pub/sub fan-out.

    `publish()` is called from the FastAPI event loop *and* from the
    pipeline's background worker thread (APScheduler) and yt-dlp progress
    hooks, so subscriber queues must be safe to write from any thread.
    `queue.Queue` (stdlib) is thread-safe by design, unlike `asyncio.Queue`
    which is only safe within a single event loop.
    """

    def __init__(self, maxsize: int = 1000):
        self._subscribers: set[queue.Queue] = set()
        self._maxsize = maxsize

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._maxsize)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # one slow/broken subscriber must not affect the others
