import time
import signal
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os

import cb_store

POLL_INTERVAL = 0.3


def _setup_logger():
    if os.name == "nt":
        log_dir = Path(os.environ.get("APPDATA", Path.home())) / "cb"
    else:
        log_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "cb"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("cb.daemon")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = RotatingFileHandler(log_dir / "daemon.log", maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)
    return logger


log = _setup_logger()


class _Win32ClipboardReader:
    """Native Windows clipboard reader. Inspects available formats before reading
    so that bitmaps/files do not trigger access-violation errors."""

    CF_UNICODETEXT = 13
    CF_TEXT = 1

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._wintypes = wintypes

        self._user32.OpenClipboard.argtypes = [wintypes.HWND]
        self._user32.OpenClipboard.restype = wintypes.BOOL
        self._user32.CloseClipboard.argtypes = []
        self._user32.CloseClipboard.restype = wintypes.BOOL
        self._user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
        self._user32.EnumClipboardFormats.restype = wintypes.UINT
        self._user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        self._user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
        self._user32.GetClipboardData.argtypes = [wintypes.UINT]
        self._user32.GetClipboardData.restype = wintypes.HANDLE
        self._kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        self._kernel32.GlobalLock.restype = wintypes.LPCVOID
        self._kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        self._kernel32.GlobalUnlock.restype = wintypes.BOOL
        self._kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
        self._kernel32.GlobalSize.restype = ctypes.c_size_t
        self._ctypes = ctypes

    def _has_text_format(self):
        return bool(self._user32.IsClipboardFormatAvailable(self.CF_UNICODETEXT)) or bool(
            self._user32.IsClipboardFormatAvailable(self.CF_TEXT)
        )

    def read_text(self):
        """Return current clipboard text, or None if clipboard does not hold text."""
        if not self._has_text_format():
            return None
        opened = False
        h = None
        locked = None
        try:
            for _ in range(5):
                if bool(self._user32.OpenClipboard(0)):
                    opened = True
                    break
                time.sleep(0.02)
            if not opened:
                return None
            h = self._user32.GetClipboardData(self.CF_UNICODETEXT)
            if not h:
                return None
            locked = self._kernel32.GlobalLock(h)
            if not locked:
                return None
            size = self._kernel32.GlobalSize(h)
            if size <= 0:
                return ""
            ptr = self._ctypes.c_wchar_p(locked)
            text = ptr.value
            if text is None:
                text = ""
            return text
        except Exception as e:
            log.warning("win32 clipboard read failed: %r", e)
            return None
        finally:
            try:
                if locked:
                    self._kernel32.GlobalUnlock(h)
            except Exception:
                pass
            try:
                if opened:
                    self._user32.CloseClipboard()
            except Exception:
                pass


class _PyperclipReader:
    """Fallback reader for non-Windows or when win32 API unavailable."""

    def __init__(self):
        import pyperclip
        self._paste = pyperclip.paste

    def read_text(self):
        try:
            value = self._paste()
        except Exception as e:
            log.warning("pyperclip paste failed: %r", e)
            return None
        if isinstance(value, str):
            return value
        return None


def _make_reader():
    if os.name == "nt":
        try:
            return _Win32ClipboardReader()
        except Exception as e:
            log.warning("win32 reader unavailable (%r), falling back to pyperclip", e)
    return _PyperclipReader()


class ClipboardWatcher:
    def __init__(self):
        self._running = False
        self._last = ""
        self._reader = _make_reader()
        self._consecutive_errors = 0

    def _safe_read(self):
        try:
            value = self._reader.read_text()
        except Exception as e:
            self._consecutive_errors += 1
            if self._consecutive_errors % 20 == 1:
                log.error("clipboard read unexpected error (#%d): %r", self._consecutive_errors, e)
            return None
        else:
            self._consecutive_errors = 0
            return value

    def run(self):
        cb_store.init_db()
        self._running = True
        initial = self._safe_read()
        if isinstance(initial, str):
            self._last = initial

        def _stop(signum, frame):
            self._running = False

        try:
            signal.signal(signal.SIGINT, _stop)
            if hasattr(signal, "SIGTERM"):
                signal.signal(signal.SIGTERM, _stop)
        except Exception:
            pass

        msg = "[cb] daemon started, watching clipboard (reader: %s)...\n" % type(self._reader).__name__
        sys.stderr.write(msg)
        sys.stderr.flush()
        log.info(msg.strip())

        while self._running:
            current = self._safe_read()
            if current is not None and current != self._last:
                if current.strip():
                    cb_store.add_entry(current)
                self._last = current
            time.sleep(POLL_INTERVAL)

        sys.stderr.write("[cb] daemon stopped.\n")
        sys.stderr.flush()
        log.info("daemon stopped")
