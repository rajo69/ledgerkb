r"""Tier-0 RTF. Enough for documents that are text with a little formatting.

RTF is a plain-text container: the bytes already are the text, wrapped in groups,
control words and escapes. That makes a dependency unnecessary, and also
undesirable, because the libraries that flatten RTF to a string discard the
paragraph styles, and those styles are the only thing in the format that carries
a heading tree. A parser that returned no headings would satisfy the port and
lose the citation path ("Minutes > Item 4 > Decision") that makes a citation
readable.

Recovered: paragraph text, headings (stylesheet names and ``\outlinelevel``),
tabs, line and page breaks, table cell text in reading order, and the escape
forms (``\\``, ``\'hh``, ``\uN``, control symbols).

Dropped: images and embedded objects (reported as warnings), list numbering, and
table geometry, so a table becomes tab-separated cell text. Hence a
``parse_quality`` of 0.8 rather than the 1.0 a format scores when the bytes are
already exactly the text.

Hidden text (``\v``) and tracked-change deletions are the reason this parser
carries an invisible-text defence at all. Word will hide a run on request, and
what a reviewer sees on the page is then not what the model reads. Hidden runs
are kept out of the text and reported as ``hidden:<offset>:<text>`` warnings,
the same shape ``parsers/html.py`` uses, which the sanitiser turns into a
quarantine record. Dropped, but never undocumented.
"""

from __future__ import annotations

import codecs
import re

from ledgerkb.core.errors import ParseError
from ledgerkb.core.ports import Heading, ParsedDocument, ParseHint

# Groups whose contents are never document text. Anything flagged ``\*`` is
# ignorable by definition, which covers everything not named here.
SKIP_DESTINATIONS = frozenset(
    {
        "fonttbl", "colortbl", "stylesheet", "listtable", "listoverridetable",
        "info", "pict", "object", "objdata", "themedata", "colorschememapping",
        "latentstyles", "datastore", "rsidtbl", "generator", "xmlnstbl", "pgptbl",
        "header", "headerl", "headerr", "headerf",
        "footer", "footerl", "footerr", "footerf",
        "footnote", "fldinst", "xe", "tc", "tcn", "nonshppict", "shppict", "mmathPr",
    }
)

# Groups that are skipped but worth telling the operator about, because
# something visible in the source document is absent from the text.
NOTABLE_SKIPS = {"pict": "image", "object": "embedded object"}

# Control words that hide the run that follows them, within their group.
HIDING = frozenset({"v", "deleted"})

# Control words that emit a character rather than setting state.
LITERALS = {
    "line": "\n", "softline": "\n", "tab": "\t", "cell": "\t", "nestcell": "\t",
    "emdash": "\u2014", "endash": "\u2013", "bullet": "\u2022",
    "lquote": "\u2018", "rquote": "\u2019",
    "ldblquote": "\u201c", "rdblquote": "\u201d",
    "enspace": "\u2002", "emspace": "\u2003", "qmspace": "\u2005",
    "zwnj": "\u200c", "zwj": "\u200d",
}

# Control symbols: a backslash followed by one non-alphabetic character.
SYMBOLS = {
    "\\": "\\", "{": "{", "}": "}",
    "~": "\u00a0",   # non-breaking space
    "_": "\u2011",   # non-breaking hyphen
    "-": "",         # optional hyphen: a hint to the renderer, not a character
    ":": "", "|": "",
}

# Control words that end the current paragraph.
PARAGRAPH_BREAKS = frozenset({"par", "sect", "page", "row", "nestrow"})

_UTF8_BOM = b"\xef\xbb\xbf"
_STYLE_NUMBER = re.compile(r"\\s(\d+)(?![a-zA-Z0-9])")
_CONTROL_RUN = re.compile(r"\\[a-zA-Z]+-?\d*[ ]?|\\[^a-zA-Z]")
_HEADING_STYLE = re.compile(r"^heading\s*([1-6])$", re.IGNORECASE)
_ANSICPG = re.compile(r"\\ansicpg(\d+)")


class _NotRtfError(ValueError):
    """These bytes are not RTF at all.

    Distinct from a malformed escape inside a document that is otherwise
    readable. Only this aborts the file; everything recoverable is a warning.
    """


def _is_alpha(ch: str) -> bool:
    """ASCII letters only.

    ``str.isalpha`` is Unicode-aware, and the source has been decoded latin-1 so
    that one character is one byte. Bytes 0xC0 to 0xFF are letters to Python and
    would be absorbed into the control word they follow, which silently eats the
    control word, the character, or both.
    """
    return "a" <= ch <= "z" or "A" <= ch <= "Z"


def _is_digit(ch: str) -> bool:
    """ASCII digits only. 0xB2, 0xB3 and 0xB9 are digits to ``str.isdigit``."""
    return "0" <= ch <= "9"


class RtfParser:
    name = "rtf"
    extensions = (".rtf",)

    def can_parse(self, mime: str, path: str) -> bool:
        return mime in {"application/rtf", "text/rtf"} or path.lower().endswith(
            self.extensions
        )

    def parse(self, data: bytes, hint: ParseHint) -> ParsedDocument:
        uri = hint.uri or hint.filename or "<bytes>"
        try:
            text, headings, warnings = _strip_control_words(data)
        except _NotRtfError as exc:
            raise ParseError(uri, f"not readable as RTF: {exc}") from exc

        return ParsedDocument(
            text=text,
            parser=self.name,
            parse_quality=0.8 if text.strip() else 0.0,
            mime="application/rtf",
            headings=headings,
            title=headings[0].text if headings else None,
            warnings=warnings,
        )


def _strip_control_words(data: bytes) -> tuple[str, list[Heading], list[str]]:
    r"""Scan RTF into text, headings and warnings.

    Decoding is latin-1 rather than UTF-8 so that one source character is one
    source byte: ``\'hh`` escapes, and any raw high bytes a non-conformant writer
    emitted, are then resolved together through the document's own code page.

    Offsets are recorded at the moment text is appended, never recovered by
    searching afterwards. Everything a paragraph produces is buffered, and the
    heading offset is taken when that buffer is flushed, so the offset is a real
    index into the returned string by construction.
    """
    if data.startswith(_UTF8_BOM):
        data = data[len(_UTF8_BOM) :]
    src = data.decode("latin-1")
    if not src.lstrip(" \t\r\n").startswith("{\\rtf"):
        raise _NotRtfError("missing the {\\rtf header")

    codec = _codec_for(src)
    style_levels = _stylesheet_levels(src)

    parts: list[str] = []
    headings: list[Heading] = []
    warnings: list[str] = []
    cursor = 0

    para: list[str] = []           # text of the paragraph being built
    hidden_run: list[str] = []     # text of the hidden run being skipped
    para_level: int | None = None  # heading level, if this paragraph is one
    raw = bytearray()              # consecutive \'hh bytes, decoded together
    high_surrogate: int | None = None

    uc = 1                         # \uN replacement characters to skip
    hidden = False
    stack: list[tuple[int, bool]] = []
    depth = 0
    skip_at: int | None = None     # skipping while depth >= this

    def target() -> list[str]:
        return hidden_run if hidden else para

    def flush_bytes() -> None:
        """Decode buffered raw bytes as one run, so multi-byte pages work."""
        nonlocal raw
        if raw:
            target().append(bytes(raw).decode(codec, errors="replace"))
            raw = bytearray()

    def emit(chunk: str) -> None:
        nonlocal high_surrogate
        flush_bytes()
        high_surrogate = None   # anything else ends an unpaired surrogate
        target().append(chunk)

    def flush_hidden() -> None:
        """Report a hidden run in the shape the sanitiser quarantines."""
        flush_bytes()
        text = "".join(hidden_run).strip()
        hidden_run.clear()
        if text:
            warnings.append(f"hidden:{cursor}:{text[:400]}")

    def end_paragraph() -> None:
        """Close the current paragraph and record its heading, if it is one."""
        nonlocal cursor, para_level
        flush_hidden()
        flush_bytes()
        text = "".join(para).strip()
        para.clear()
        if text:
            # char_start is taken here, before the append, so it indexes the
            # returned string exactly.
            if para_level is not None:
                headings.append(Heading(char_start=cursor, level=para_level, text=text))
            parts.append(text)
            parts.append("\n\n")
            cursor += len(text) + 2
        para_level = None

    i = 0
    n = len(src)
    while i < n:
        ch = src[i]

        if ch == "{":
            stack.append((uc, hidden))
            depth += 1
            i += 1
            continue

        if ch == "}":
            if skip_at is not None and depth == skip_at:
                skip_at = None
            depth -= 1
            was_hidden = hidden
            if stack:
                uc, hidden = stack.pop()
            if was_hidden and not hidden:
                flush_hidden()
            i += 1
            continue

        if ch != "\\":
            if ch in "\r\n":
                # Literal newlines in the source are formatting, not text. The
                # document's own breaks arrive as \par and \line.
                i += 1
                continue
            if skip_at is None:
                if ord(ch) > 127:
                    high_surrogate = None
                    raw.append(ord(ch))   # unescaped high byte, same code page
                else:
                    emit(ch)
            i += 1
            continue

        # --- a control word or a control symbol ------------------------------
        i += 1
        if i >= n:
            break
        c = src[i]

        if c == "'":
            hex_pair = src[i + 1 : i + 3]
            i += 3
            if skip_at is None:
                try:
                    value = int(hex_pair, 16)
                except ValueError:
                    # One bad escape does not make the document unreadable. The
                    # pipeline's rule is that a recoverable problem is a warning.
                    emit("\ufffd")
                    warnings.append(f"bad hex escape {hex_pair!r} at offset {cursor}")
                else:
                    high_surrogate = None
                    raw.append(value)
            continue

        if not _is_alpha(c):
            # A backslash before a line break is a paragraph mark, not a symbol.
            if c in "\r\n":
                i += 1
                if c == "\r" and i < n and src[i] == "\n":
                    i += 1
                if skip_at is None:
                    end_paragraph()
                continue
            i += 1
            if c == "*":
                if skip_at is None:      # \* marks the enclosing group ignorable
                    skip_at = depth
                continue
            if skip_at is None and (symbol := SYMBOLS.get(c)):
                emit(symbol)
            continue

        j = i
        while j < n and _is_alpha(src[j]):
            j += 1
        word = src[i:j]

        k = j
        if k < n and (src[k] == "-" or _is_digit(src[k])):
            k += 1
            while k < n and _is_digit(src[k]):
                k += 1
        digits = src[j:k]
        # A lone "-" is malformed. Treat it as no parameter rather than letting
        # int() abort a document that is otherwise perfectly readable.
        param = int(digits) if digits and digits != "-" else None

        # Exactly one trailing space is the delimiter and is not text.
        if k < n and src[k] == " ":
            k += 1
        i = k

        if word == "bin" and param and param > 0:
            i += param          # binary payload, counted in bytes
            continue

        if word in SKIP_DESTINATIONS:
            # Warn even when already inside a skipped group: Word wraps every
            # picture as {\*\shppict{\pict}}, so the \pict is always nested
            # inside an ignorable destination. Deduplicated by offset, because
            # Word writes the same image twice as \shppict and \nonshppict.
            if note := NOTABLE_SKIPS.get(word):
                message = f"skipped {note} at offset {cursor}"
                if message not in warnings:
                    warnings.append(message)
            if skip_at is None:
                skip_at = depth
            continue

        if skip_at is not None:
            continue

        if word in HIDING:
            was_hidden = hidden
            hidden = param != 0
            if was_hidden and not hidden:
                flush_hidden()
            continue

        if word == "uc" and param is not None:
            uc = max(0, param)
            continue

        if word == "u" and param is not None:
            flush_bytes()
            code = param + 0x10000 if param < 0 else param
            if 0xD800 <= code <= 0xDBFF:
                high_surrogate = code
            elif 0xDC00 <= code <= 0xDFFF and high_surrogate is not None:
                combined = 0x10000 + ((high_surrogate - 0xD800) << 10) + (code - 0xDC00)
                target().append(chr(combined))
                high_surrogate = None
            elif code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF:
                target().append(chr(code))
                high_surrogate = None
            i = _skip_replacements(src, i, uc)
            continue

        if word == "pard":
            para_level = None
            continue

        if word == "outlinelevel" and param is not None and 0 <= param <= 5:
            para_level = param + 1
            continue

        if word == "s" and param is not None and param in style_levels:
            para_level = style_levels[param]
            continue

        if word in PARAGRAPH_BREAKS:
            end_paragraph()
            continue

        if literal := LITERALS.get(word):
            emit(literal)
            continue

    end_paragraph()

    # A trailing separator only. Every recorded offset lies before it, so
    # removing it cannot move one.
    text = "".join(parts).rstrip("\n")
    return text, headings, warnings


def _skip_replacements(src: str, i: int, uc: int) -> int:
    r"""Step over the ``uc`` ANSI characters that follow a ``\uN``.

    They are the same character written again for readers that cannot do
    Unicode. Counting them wrong is the classic RTF bug: it either swallows real
    text or leaks a mojibake duplicate of every non-ASCII character.
    """
    n = len(src)
    remaining = uc
    while remaining > 0 and i < n:
        ch = src[i]
        if ch in "{}":
            break                      # a group boundary ends the run
        if ch == "\\":
            if i + 1 < n and src[i + 1] == "'":
                i += 4                 # \'hh is one character
            elif i + 1 < n and _is_alpha(src[i + 1]):
                j = i + 1
                while j < n and _is_alpha(src[j]):
                    j += 1
                while j < n and (src[j] == "-" or _is_digit(src[j])):
                    j += 1
                if j < n and src[j] == " ":
                    j += 1
                i = j                  # a control word is one character
            else:
                i += 2                 # a control symbol is one character
        else:
            i += 1
        remaining -= 1
    return i


def _codec_for(src: str) -> str:
    r"""The code page for ``\'hh`` escapes, from ``\ansicpg``.

    cp1252 is the fallback because it is what Word writes when it says nothing,
    and because it cannot raise on a byte the way a stricter codec would.
    """
    if m := _ANSICPG.search(src):
        name = f"cp{m.group(1)}"
        try:
            codecs.lookup(name)
        except LookupError:
            return "cp1252"
        return name
    return "cp1252"


def _stylesheet_levels(src: str) -> dict[int, int]:
    r"""Map style numbers to heading levels by reading ``{\stylesheet}``.

    Word writes a heading as a numbered style reference (``\s1``) whose human
    name lives in the stylesheet. Without this map every heading in a Word
    document is invisible, and Word is what writes most RTF worth ingesting.
    """
    start = src.find("{\\stylesheet")
    if start == -1:
        return {}

    levels: dict[int, int] = {}
    depth = 0
    entry_start = -1
    i = start
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == "\\":
            i += 2                     # never read an escaped brace as a brace
            continue
        if ch == "{":
            depth += 1
            if depth == 2:
                entry_start = i + 1
        elif ch == "}":
            depth -= 1
            if depth == 1 and entry_start != -1:
                _read_style_entry(src[entry_start:i], levels)
                entry_start = -1
            elif depth == 0:
                break
        i += 1
    return levels


def _drop_nested_groups(entry: str) -> str:
    r"""Remove balanced ``{...}`` spans from one stylesheet entry.

    Word gives its built-in heading styles a keyboard shortcut, which it writes
    as a nested ``{\*\keycode ...}`` group inside the style definition. Left in
    place, the group's braces and contents end up in the style name and no
    heading is ever recognised in a Word document.
    """
    out: list[str] = []
    depth = 0
    i = 0
    n = len(entry)
    while i < n:
        ch = entry[i]
        if ch == "\\" and i + 1 < n:
            if depth == 0:
                out.append(entry[i : i + 2])
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
        i += 1
    return "".join(out)


def _read_style_entry(entry: str, levels: dict[int, int]) -> None:
    r"""One ``{\s1 ... heading 1;}`` definition."""
    flat = _drop_nested_groups(entry)
    number = _STYLE_NUMBER.search(flat)
    if not number:
        return
    name = _CONTROL_RUN.sub("", flat).split(";")[0].strip()
    if m := _HEADING_STYLE.match(name):
        levels[int(number.group(1))] = int(m.group(1))


__all__ = ["RtfParser"]
