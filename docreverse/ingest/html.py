"""HTML loader (headings, paragraphs, lists, tables) using only the standard library."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..models import Block


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: List[Block] = []
        self.title = ""
        self._skip = 0
        self._in_title = False
        self._lists: List[str] = []
        self._cur: Optional[Tuple[str, int, bool]] = None
        self._buf: List[str] = []
        self._row: Optional[List[Tuple[str, str]]] = None   # (tag, text)
        self._headers: List[str] = []

    # ---- helpers
    def _begin(self, kind: str, level: int = 0, ordered: bool = False) -> None:
        self._end()
        self._cur, self._buf = (kind, level, ordered), []

    def _end(self) -> None:
        if self._cur is None:
            return
        kind, level, ordered = self._cur
        text = " ".join("".join(self._buf).split())
        self._cur, self._buf = None, []
        if not text:
            return
        if kind == "cell" and self._row is not None:
            self._row.append(("cell", text))
        else:
            self.blocks.append(Block(kind, text, level, ordered))

    # ---- parser callbacks
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("ol", "ul"):
            self._lists.append(tag)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._begin("heading", int(tag[1]))
        elif tag == "p":
            self._begin("paragraph")
        elif tag == "li":
            self._begin("list_item", max(len(self._lists) - 1, 0), bool(self._lists and self._lists[-1] == "ol"))
        elif tag == "table":
            self._headers = []
        elif tag == "tr":
            self._end()
            self._row = []
        elif tag in ("td", "th"):
            self._begin("cell")
            if tag == "th" and self._row is not None:
                self._row.append(("th_marker", ""))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = max(self._skip - 1, 0)
        elif tag == "title":
            self._in_title = False
        elif tag in ("ol", "ul"):
            if self._lists:
                self._lists.pop()
            self._end()
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th"):
            self._end()
        elif tag == "tr":
            self._end()
            row, self._row = self._row or [], None
            cells = [t for k, t in row if k == "cell"]
            is_header = any(k == "th_marker" for k, _ in row)
            if cells:
                if is_header or not self._headers:
                    self._headers = cells
                    if not is_header:   # first row without <th>: treat as header
                        pass
                elif len(cells) == len(self._headers):
                    self.blocks.append(Block("table_row", "; ".join(f"{h}: {c}" for h, c in zip(self._headers, cells) if c)))
                else:
                    self.blocks.append(Block("table_row", " | ".join(cells)))

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
        elif self._cur is not None:
            self._buf.append(data)


def parse_html(html: str) -> Tuple[List[Block], str]:
    c = _Collector()
    c.feed(html)
    c._end()
    return c.blocks, " ".join(c.title.split())


def load_html(path: Path) -> Tuple[List[Block], Dict[str, str]]:
    html = path.read_bytes().decode("utf-8", errors="replace")
    blocks, title = parse_html(html)
    return blocks, ({"title": title} if title else {})
