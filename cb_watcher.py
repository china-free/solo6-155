import time
import signal
import sys

import pyperclip

import cb_store

POLL_INTERVAL = 0.5


class ClipboardWatcher:
    def __init__(self):
        self._running = False
        self._last = ""

    def _try_get(self):
        try:
            return pyperclip.paste()
        except Exception:
            return self._last

    def run(self):
        cb_store.init_db()
        self._running = True
        self._last = self._try_get()

        def _stop(signum, frame):
            self._running = False

        signal.signal(signal.SIGINT, _stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _stop)

        sys.stderr.write("[cb] daemon started, watching clipboard...\n")
        sys.stderr.flush()

        while self._running:
            try:
                current = self._try_get()
                if current and current != self._last:
                    if isinstance(current, str):
                        cb_store.add_entry(current)
                    self._last = current
            except Exception:
                pass
            time.sleep(POLL_INTERVAL)

        sys.stderr.write("[cb] daemon stopped.\n")
        sys.stderr.flush()
