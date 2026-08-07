"""HTML — ``selectolax`` for the DOM, ``trafilatura`` for boilerplate removal.

This parser carries most of the invisible-text defence, because HTML is where
hidden content is easiest to author: a comment, ``display:none``, or white text
on a white background all render as nothing to a human and as instructions to a
model.

Anything dropped for being invisible is reported as a ``hidden:<offset>:<text>``
warning, which the sanitiser turns into a quarantine record. Dropped, but never
undocumented — the operator gets to see what was in the file.
"""

from __future__ import annotations

import re

from ledgerkb.core.errors import ParseError
from ledgerkb.core.ports import Heading, ParsedDocument, ParseHint

BLOCK_TAGS = {
    "p", "div", "section", "article", "li", "tr", "br", "blockquote", "pre",
    "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "figcaption",
}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
DROP_TAGS = {"script", "style", "noscript", "template", "svg", "canvas"}

_HIDDEN_STYLE = re.compile(
    r"(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?!\.)|"
    r"font-size\s*:\s*0|text-indent\s*:\s*-\d{3,}|"
    r"(?:left|top)\s*:\s*-\d{4,}px)",
    re.IGNORECASE,
)
_COLOUR = re.compile(r"(?<!-)\bcolor\s*:\s*([^;]+)", re.IGNORECASE)
_BACKGROUND = re.compile(r"background(?:-color)?\s*:\s*([^;]+)", re.IGNORECASE)

_NAMED = {
    "white": (255, 255, 255), "black": (0, 0, 0), "transparent": (255, 255, 255),
}


class HtmlParser:
    name = "selectolax"
    extensions = (".html", ".htm", ".xhtml")

    def can_parse(self, mime: str, path: str) -> bool:
        return "html" in mime or path.lower().endswith(self.extensions)

    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument:
        from ledgerkb.ingest.parsers.plain import decode

        uri = hint.uri or hint.filename or "<bytes>"
        html = decode(data, uri)
        parser = _import_selectolax(uri)

        try:
            tree = parser(html)
        except Exception as exc:
            raise ParseError(uri, f"unparseable HTML: {exc}") from exc

        warnings: list[str] = []
        parts: list[str] = []
        headings: list[Heading] = []
        cursor = 0

        # Comments never render. They are a favourite injection channel
        # precisely because reviewers read the rendered page.
        for comment in re.findall(r"<!--(.*?)-->", html, flags=re.DOTALL):
            if comment.strip():
                warnings.append(f"hidden:{cursor}:{comment.strip()[:400]}")

        body = tree.body or tree.root
        if body is None:
            return ParsedDocument(text="", parser=self.name, parse_quality=0.0,
                                  mime=hint.mime or "text/html", warnings=warnings)

        for node in body.traverse(include_text=True):
            tag = node.tag
            if tag in DROP_TAGS:
                continue
            if tag == "-text":
                text = (node.text() or "").strip()
                if not text:
                    continue
                if _is_hidden(node):
                    warnings.append(f"hidden:{cursor}:{text[:400]}")
                    continue
                parts.append(text)
                cursor += len(text) + 1
                continue
            if tag in HEADING_TAGS:
                label = (node.text(deep=True) or "").strip()
                if label and not _is_hidden(node):
                    headings.append(
                        Heading(char_start=cursor, level=int(tag[1]), text=label)
                    )
            if tag in BLOCK_TAGS and parts and parts[-1] != "":
                parts.append("")
                cursor += 1

        text = "\n".join(parts)
        text = re.sub(r"\n{3,}", "\n\n", text)

        title_node = tree.css_first("title")
        title = (title_node.text() or "").strip() if title_node else None
        if not title and headings:
            title = headings[0].text

        return ParsedDocument(
            text=text,
            parser=self.name,
            parse_quality=1.0 if text.strip() else 0.0,
            mime=hint.mime or "text/html",
            headings=headings,
            title=title or hint.filename,
            warnings=warnings,
        )


def _import_selectolax(uri: str):  # noqa: ANN202
    try:
        from selectolax.parser import HTMLParser
    except ImportError as exc:
        raise ParseError(
            uri, "HTML support needs the 'local' extra: pip install 'ledgerkb[local]'"
        ) from exc
    return HTMLParser


def _is_hidden(node) -> bool:  # noqa: ANN001 - selectolax node
    """Walk up the tree: a hidden ancestor hides its descendants."""
    current = node
    depth = 0
    while current is not None and depth < 40:
        attrs = getattr(current, "attributes", None) or {}
        if "hidden" in attrs:
            return True
        if attrs.get("aria-hidden") == "true":
            return True
        style = attrs.get("style") or ""
        if style:
            if _HIDDEN_STYLE.search(style):
                return True
            if _text_matches_background(style):
                return True
        current = current.parent
        depth += 1
    return False


def _text_matches_background(style: str) -> bool:
    """White-on-white and its relatives.

    Only an exact match counts. Guessing at low-contrast pairs would start
    dropping legitimate design choices, and a false positive here silently
    removes real content from the record.
    """
    fg, bg = _COLOUR.search(style), _BACKGROUND.search(style)
    if not fg or not bg:
        return False
    a, b = _rgb(fg.group(1)), _rgb(bg.group(1))
    return a is not None and a == b


def _rgb(value: str) -> tuple[int, int, int] | None:
    v = value.strip().lower().rstrip(";").strip()
    if v in _NAMED:
        return _NAMED[v]
    if m := re.fullmatch(r"#([0-9a-f]{3})", v):
        return tuple(int(c * 2, 16) for c in m.group(1))  # type: ignore[return-value]
    if m := re.fullmatch(r"#([0-9a-f]{6})", v):
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    if m := re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,[^)]*)?\)", v):
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


__all__ = ["HtmlParser"]
