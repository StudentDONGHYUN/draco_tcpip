import pytest
from multiprocessing import shared_memory

np = pytest.importorskip("numpy")

from draco_roundtrip.draco_roundtrip.nodes.stream_client import SpoolWatcher
from draco_roundtrip.draco_roundtrip.shared_memory.channel import SharedMemoryPublisher


class _FailingSock:
    def sendall(self, payload: bytes) -> None:
        raise OSError("send failure for test")


def test_spool_watcher_gc_window(tmp_path):
    watcher = SpoolWatcher(tmp_path, "frame", gc_window=2)
    for idx in range(4):
        (tmp_path / f"frame_{idx:05d}.ply").write_text("ply\n", encoding="utf-8")
    with watcher:
        discovered = watcher.drain_initial()
    assert len(discovered) == 4
    assert len(watcher._known) <= 2
    watcher.mark_consumed(discovered[0])
    assert discovered[0].name in watcher._retired_set
    assert discovered[0].name not in watcher._known


def test_shared_memory_publisher_unlinks_on_failure(tmp_path):
    publisher = SharedMemoryPublisher("127.0.0.1", 0)
    publisher._sock = _FailingSock()  # bypass real socket connection
    recorded: list[str] = []
    original_schedule = publisher._schedule_unlink

    def _capture(name: str) -> None:
        recorded.append(name)
        original_schedule(name)

    publisher._schedule_unlink = _capture  # type: ignore[assignment]
    with pytest.raises(OSError):
        publisher.publish("frame", np.ones((2, 3), dtype=np.float32))
    assert recorded and all(name.startswith("draco_stream_") for name in recorded if name)
    for name in recorded:
        if not name:
            continue
        with pytest.raises(FileNotFoundError):
            shared_memory.SharedMemory(name=name)
    publisher.close()
