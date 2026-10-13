import logging

from triagesim.logs import Throttle, configure, log


def test_throttle_logs_on_status_change_and_every_step(caplog):
    configure()
    log.propagate = True                      # let pytest capture it
    try:
        with caplog.at_level(logging.INFO, logger="triagesim"):
            t = Throttle("Model x", step=50)
            for done in range(0, 101, 10):
                t({"status": "downloading", "completed": done, "total": 100})
            t({"status": "success"})
        lines = [r.getMessage() for r in caplog.records]
        assert lines == ["Model x: downloading 0%", "Model x: downloading 50%", "Model x: downloading 100%",
                         "Model x: success"]
    finally:
        log.propagate = False
