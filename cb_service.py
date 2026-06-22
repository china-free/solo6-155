import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import cb_store

HIGHLIGHT_BEGIN = "\x01"
HIGHLIGHT_END = "\x02"

MAX_PREVIEW_LEN = 400
DEFAULT_SEARCH_LIMIT = 500
DEFAULT_LIST_LIMIT = 50


@dataclass
class ClipboardEntry:
    id: int
    content: str
    created_at: float

    @property
    def time_str(self) -> str:
        return datetime.fromtimestamp(self.created_at).strftime("%H:%M:%S")

    @property
    def date_str(self) -> str:
        return datetime.fromtimestamp(self.created_at).strftime("%Y-%m-%d %H:%M:%S")

    @property
    def char_count(self) -> int:
        return len(self.content)

    @property
    def line_count(self) -> int:
        return self.content.count("\n") + 1


@dataclass
class SearchResultItem:
    entry: ClipboardEntry
    preview: str
    highlighted_content: str
    matched: bool


class SearchService:
    """
    Middle layer between storage and UI.
    - Owns search logic (fuzzy / regex / today filter)
    - Owns data formatting (time, truncation, highlight)
    - Returns clean data structures for UI to render.
    """

    def __init__(self):
        cb_store.init_db()

    @staticmethod
    def _truncate_one_line(text: str, max_len: int) -> str:
        text = (text or "").replace("\r", "").replace("\t", "    ")
        lines = text.split("\n")
        first = lines[0]
        extra = len(lines) - 1
        if len(first) > max_len:
            return first[: max_len - 1] + "…"
        if extra > 0:
            return first + f" ⏎ ({extra} more lines)"
        return first

    @staticmethod
    def _apply_highlight(text: str, query: str, use_regex: bool) -> str:
        if not query:
            return text
        try:
            if use_regex:
                pat = re.compile(query, re.IGNORECASE)
            else:
                pat = re.compile(re.escape(query), re.IGNORECASE)
        except re.error:
            return text
        out = []
        last = 0
        for m in pat.finditer(text):
            out.append(text[last:m.start()])
            out.append(HIGHLIGHT_BEGIN + m.group(0) + HIGHLIGHT_END)
            last = m.end()
        out.append(text[last:])
        return "".join(out)

    @staticmethod
    def _matches(content: str, query: str, use_regex: bool) -> bool:
        if not query:
            return True
        try:
            if use_regex:
                return bool(re.search(query, content, re.IGNORECASE))
            else:
                return query.lower() in content.lower()
        except re.error:
            return True

    @staticmethod
    def _today_start_ts() -> float:
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def _fetch_raw(self, today_only: bool, limit: int) -> List[ClipboardEntry]:
        since = self._today_start_ts() if today_only else None
        rows = cb_store.get_entries(since_ts=since, limit=limit)
        return [ClipboardEntry(id=r["id"], content=r["content"], created_at=r["created_at"]) for r in rows]

    def search(
        self,
        query: Optional[str] = None,
        use_regex: bool = False,
        today_only: bool = True,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> List[SearchResultItem]:
        q = (query or "").strip()
        entries = self._fetch_raw(today_only=today_only, limit=limit)
        results = []
        for entry in entries:
            matched = self._matches(entry.content, q, use_regex)
            if q and not matched:
                continue
            preview = self._truncate_one_line(entry.content, 180)
            highlighted_preview = self._apply_highlight(preview, q, use_regex)
            full = entry.content
            if len(full) > MAX_PREVIEW_LEN:
                full = full[:MAX_PREVIEW_LEN] + "\n... (truncated)"
            highlighted_full = self._apply_highlight(full, q, use_regex)
            results.append(
                SearchResultItem(
                    entry=entry,
                    preview=highlighted_preview,
                    highlighted_content=highlighted_full,
                    matched=matched,
                )
            )
        return results

    def list_recent(self, limit: int = DEFAULT_LIST_LIMIT, today_only: bool = False) -> List[SearchResultItem]:
        return self.search(query=None, use_regex=False, today_only=today_only, limit=limit)
