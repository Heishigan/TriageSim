"""Readable progress messages in the terminal window, like ComfyUI.

Everything important (data checks, cohort and case builds, downloads, runs, errors)
is logged here so the black window shows what the app is doing.
"""
from __future__ import annotations

import logging
import sys

log = logging.getLogger("triagesim")


class _StdoutHandler(logging.StreamHandler):
    """Always writes to the current sys.stdout (also when it is swapped, e.g. in tests)."""

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, _value):
        pass


def configure() -> None:
    if log.handlers:
        return
    handler = _StdoutHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s %(message)s", "%H:%M:%S"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


class Throttle:
    """Log a progress line only when the percentage moves by ``step`` or the status changes."""

    def __init__(self, label: str, step: int = 10):
        self.label, self.step, self.last_pct, self.last_status = label, step, -100, None

    def __call__(self, p: dict) -> None:
        status, total = p.get("status", ""), p.get("total") or 0
        pct = int(100 * p.get("completed", 0) / total) if total else None
        if status != self.last_status or (pct is not None and pct >= self.last_pct + self.step):
            log.info("%s: %s%s", self.label, status, f" {pct}%" if pct is not None else "")
            self.last_status, self.last_pct = status, pct if pct is not None else self.last_pct
