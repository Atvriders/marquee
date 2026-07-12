import queue
import threading

import pytest

from marquee.api.sse import Broadcaster


def test_fanout_to_all_subscribers():
    b = Broadcaster()
    q1 = b.subscribe()
    q2 = b.subscribe()
    b.publish({"a": 1})
    assert q1.get_nowait() == {"a": 1}
    assert q2.get_nowait() == {"a": 1}


def test_unsubscribe_stops_delivery():
    b = Broadcaster()
    q1 = b.subscribe()
    q2 = b.subscribe()
    b.unsubscribe(q2)
    b.publish({"b": 2})
    assert q1.get_nowait() == {"b": 2}
    with pytest.raises(queue.Empty):
        q2.get_nowait()


def test_publish_with_no_subscribers_is_noop():
    b = Broadcaster()
    b.publish({"c": 3})  # must not raise


def test_full_subscriber_queue_does_not_block_healthy_subscribers():
    b = Broadcaster(maxsize=1)
    broken = b.subscribe()
    broken.put_nowait({"pre-fill": True})  # saturate this subscriber's queue
    healthy = b.subscribe()

    b.publish({"d": 4})  # must not raise despite `broken` being full

    # Healthy subscriber still receives the event...
    assert healthy.get_nowait() == {"d": 4}
    # ...while the full one silently dropped it (still holds only the pre-fill item).
    assert broken.get_nowait() == {"pre-fill": True}
    with pytest.raises(queue.Empty):
        broken.get_nowait()


def test_publish_from_worker_thread_is_received_by_subscriber():
    # Proves Broadcaster is safe to call from a non-event-loop thread, as the
    # pipeline's APScheduler worker thread and yt-dlp progress hooks do.
    b = Broadcaster()
    q = b.subscribe()

    t = threading.Thread(target=b.publish, args=({"e": 5},))
    t.start()
    t.join(timeout=5)
    assert not t.is_alive()

    assert q.get(timeout=5) == {"e": 5}
