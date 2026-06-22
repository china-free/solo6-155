import re
import sys
from datetime import datetime

import pyperclip
from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.filters import has_focus
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.processors import Processor, Transformation, TransformationInput
from prompt_toolkit.formatted_text import HTML, to_formatted_text, fragment_list_to_text
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import SearchToolbar
from prompt_toolkit.key_binding.bindings.focus import focus_next, focus_previous

import cb_store

MAX_PREVIEW_LEN = 400
HIGHLIGHT_BEGIN = "\x01"
HIGHLIGHT_END = "\x02"


def _apply_highlight(text: str, query: str, use_regex: bool) -> str:
    if not query:
        return text
    try:
        if use_regex:
            pat = re.compile(query, re.IGNORECASE)
        else:
            pat = re.compile(re.escape(query), re.IGNORECASE)
        out = []
        last = 0
        for m in pat.finditer(text):
            out.append(text[last:m.start()])
            out.append(HIGHLIGHT_BEGIN + m.group(0) + HIGHLIGHT_END)
            last = m.end()
        out.append(text[last:])
        return "".join(out)
    except Exception:
        return text


def _highlighted_to_html(text: str) -> str:
    text = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace(HIGHLIGHT_BEGIN, '<span bgansiyellow fg="black">')
    text = text.replace(HIGHLIGHT_END, "</span>")
    return text


def _ts_to_str(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _truncate(s: str, n: int) -> str:
    s = (s or "").replace("\r", "").replace("\t", "    ")
    lines = s.split("\n")
    first = lines[0]
    extra = len(lines) - 1
    if len(first) > n:
        return first[: n - 1] + "…"
    if extra > 0:
        return first + f" ⏎ ({extra} more lines)"
    return first


class _EntriesControl(FormattedTextControl):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.selected_index = 0


def interactive_search(query: str = None, use_regex: bool = False, today_only: bool = True):
    cb_store.init_db()
    kb = KeyBindings()
    initial_query = query or ""

    search_field = Buffer()
    if initial_query:
        search_field.set_document(Document(initial_query, cursor_position=len(initial_query)))

    def _get_entries():
        q = search_field.text
        return cb_store.search_entries(q.strip() or None, use_regex=use_regex, today_only=today_only)

    entries = [_get_entries()]

    def _reload_entries():
        entries[0] = _get_entries()

    selected = [0]

    def _get_title_text():
        _reload_entries()
        total = len(entries[0])
        if total == 0:
            selected[0] = 0
            return [("class:title", f" 0 matches | ↓↑ navigate | Enter copy | Esc exit\n")]
        if selected[0] >= total:
            selected[0] = total - 1
        scope = "today" if today_only else "all"
        return [("class:title", f" {total} matches ({scope}) | #{selected[0] + 1} | ↓↑ navigate | Enter copy | Esc exit\n")]

    def _get_list_text():
        result = []
        rows = entries[0]
        if not rows:
            return [("class:empty", " (no results)\n")]
        q = search_field.text
        for idx, row in enumerate(rows):
            mark = "> " if idx == selected[0] else "  "
            ts = _ts_to_str(row["created_at"])
            preview = _apply_highlight(_truncate(row["content"], 180), q, use_regex)
            preview_html = _highlighted_to_html(preview)
            prefix_class = "selected-prefix" if idx == selected[0] else "prefix"
            line_class = "selected-line" if idx == selected[0] else "line"
            fragments = to_formatted_text(
                HTML(
                    f'<span class="{prefix_class}">{mark}[{ts}]</span>'
                    f'<span class="{line_class}"> {preview_html}</span>\n'
                )
            )
            result.extend(fragments)
        return result

    def _get_preview_text():
        rows = entries[0]
        if not rows:
            return [("class:empty", " -- nothing to preview --\n")]
        row = rows[selected[0]]
        q = search_field.text
        content = row["content"]
        if len(content) > MAX_PREVIEW_LEN:
            content = content[:MAX_PREVIEW_LEN] + "\n... (truncated)"
        highlighted = _apply_highlight(content, q, use_regex)
        html = (
            f'<span class="preview-header">=== [{_ts_to_str(row["created_at"])}] '
            f'#{row["id"]} ({len(row["content"])} chars) ===</span>\n'
            f'{_highlighted_to_html(highlighted)}'
        )
        return to_formatted_text(HTML(html))

    search_control = BufferControl(buffer=search_field)
    title_win = Window(FormattedTextControl(_get_title_text), height=1, style="class:title")
    list_win = Window(FormattedTextControl(_get_list_text), style="class:list")
    preview_win = Window(FormattedTextControl(_get_preview_text), style="class:preview", wrap_lines=True)

    root = HSplit(
        [
            Window(
                content=search_control,
                height=1,
                style="class:search",
                get_line_prefix=lambda *_: " [?] ",
            ),
            title_win,
            list_win,
            Window(height=1, char="─", style="class:separator"),
            preview_win,
        ]
    )

    def _clip_and_exit():
        rows = entries[0]
        if not rows:
            get_app().exit(result=None)
            return
        chosen = rows[selected[0]]["content"]
        try:
            pyperclip.copy(chosen)
        except Exception:
            pass
        get_app().exit(result=chosen)

    @kb.add("escape")
    def _exit(event):
        get_app().exit(result=None)

    @kb.add("enter")
    def _enter(event):
        _clip_and_exit()

    @kb.add("down")
    def _down(event):
        total = len(entries[0])
        if total > 0 and selected[0] < total - 1:
            selected[0] += 1
            get_app().invalidate()

    @kb.add("up")
    def _up(event):
        if selected[0] > 0:
            selected[0] -= 1
            get_app().invalidate()

    @kb.add("c-n")
    def _c_n(event):
        total = len(entries[0])
        if total > 0 and selected[0] < total - 1:
            selected[0] += 1
            get_app().invalidate()

    @kb.add("c-p")
    def _c_p(event):
        if selected[0] > 0:
            selected[0] -= 1
            get_app().invalidate()

    @kb.add("c-d", filter=has_focus(search_control))
    @kb.add("delete", filter=has_focus(search_control))
    def _ignore(event):
        pass

    @search_control.on_text_changed.add_handler
    def _on_change(_):
        selected[0] = 0

    style = Style(
        [
            ("title", "fg:ansigreen"),
            ("search", "bg:ansiblack fg:ansicyan"),
            ("list", "bg:ansiblack fg:ansiwhite"),
            ("preview", "bg:ansiblack fg:ansibrightwhite"),
            ("separator", "fg:ansibrightblack"),
            ("empty", "fg:ansibrightblack italic"),
            ("selected-line", "fg:ansibrightwhite bg:ansiblue"),
            ("line", "fg:ansiwhite"),
            ("selected-prefix", "fg:ansibrightyellow bold bg:ansiblue"),
            ("prefix", "fg:ansibrightblack"),
            ("preview-header", "fg:ansibrightmagenta bold"),
        ]
    )

    layout = Layout(root)
    app = Application(
        layout=layout,
        key_bindings=kb,
        style=style,
        full_screen=True,
        mouse_support=False,
        erase_when_done=False,
    )
    result = app.run()
    if result is None:
        print("(cancelled)")
    else:
        n = len(result)
        preview = result[:80].replace("\n", " ").strip()
        if n > 80:
            preview += "…"
        print(f"→ copied to clipboard ({n} chars): {preview}")
    return result
