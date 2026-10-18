"""status.json survives concurrent writers (the run loop and its heartbeat)."""
import json
import threading

from triagesim.experiment.runner import read_status, write_status


def test_concurrent_status_writes(tmp_path):
    write_status(tmp_path, state="running", done=0)
    errors = []

    def writer(key):
        try:
            for i in range(300):
                write_status(tmp_path, **{key: i})
        except Exception as exc:  # pragma: no cover - the failure we guard against
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(k,)) for k in ("done", "heartbeat", "current_case")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    status = read_status(tmp_path)
    assert status["state"] == "running" and status["done"] == 299 and status["heartbeat"] == 299
    assert json.loads((tmp_path / "status.json").read_text())
    assert not list(tmp_path.glob("*.tmp"))
