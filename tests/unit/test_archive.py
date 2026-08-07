"""ZIP guards. Every malicious fixture must be refused, loudly."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from ledgerkb.ingest.readers.archive import (
    MAX_DEPTH,
    ArchiveRejectedError,
    expand,
    is_archive,
    safe_entry_name,
)


def zip_of(entries: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, payload in entries.items():
            z.writestr(name, payload)
    return buf.getvalue()


class TestMaliciousFixtures:
    """The five hand-built archives from the fixture set."""

    def test_all_five_are_rejected(self, archives: Path) -> None:
        survived = []
        for path in sorted(archives.iterdir()):
            try:
                list(expand(path.read_bytes(), path.name))
                survived.append(path.name)
            except ArchiveRejectedError:
                pass
        assert survived == [], f"archives that were not refused: {survived}"

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("01-traversal.zip", "traversal"),
            ("02-absolute.zip", "absolute"),
            ("03-drive-letter.zip", "absolute path or drive letter"),
            ("04-bomb.zip", "compression ratio"),
            ("05-nested.zip", "nesting"),
        ],
    )
    def test_each_is_refused_for_the_right_reason(
        self, archives: Path, name: str, expected: str
    ) -> None:
        with pytest.raises(ArchiveRejectedError, match=expected):
            list(expand((archives / name).read_bytes(), name))


class TestEntryNames:
    @pytest.mark.parametrize(
        "name",
        [
            "../escape.txt",
            "a/../../escape.txt",
            "/etc/passwd",
            "C:\\Windows\\evil.txt",
            "..\\..\\escape.txt",
        ],
    )
    def test_dangerous_names_are_refused(self, name: str) -> None:
        with pytest.raises(ArchiveRejectedError):
            safe_entry_name("test.zip", name)

    def test_a_null_byte_is_refused(self) -> None:
        with pytest.raises(ArchiveRejectedError, match="null byte"):
            safe_entry_name("test.zip", "ok\x00.txt")

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("minutes.md", "minutes.md"),
            ("./minutes.md", "minutes.md"),
            ("papers/2026/minutes.md", "papers/2026/minutes.md"),
            ("papers\\2026\\minutes.md", "papers/2026/minutes.md"),
        ],
    )
    def test_ordinary_names_are_normalised(self, name: str, expected: str) -> None:
        assert safe_entry_name("test.zip", name) == expected


class TestGuards:
    def test_a_legitimate_archive_expands(self) -> None:
        members = list(expand(zip_of({
            "minutes.md": "# Minutes\n",
            "notes/site.txt": "Site note\n",
        }), "papers.zip"))
        assert {m.path for m in members} == {"minutes.md", "notes/site.txt"}
        assert members[0].depth == 0

    def test_nesting_within_the_limit_is_allowed(self) -> None:
        inner = zip_of({"deep.md": "# Deep\n"})
        middle = zip_of({"inner.zip": inner})
        outer = zip_of({"middle.zip": middle})
        members = list(expand(outer, "outer.zip"))
        assert [m.path for m in members] == ["deep.md"]
        assert members[0].depth == 2

    def test_nesting_past_the_limit_is_refused(self) -> None:
        payload = zip_of({"deep.md": "# Deep\n"})
        for i in range(MAX_DEPTH + 2):
            payload = zip_of({f"level{i}.zip": payload})
        with pytest.raises(ArchiveRejectedError, match="nesting"):
            list(expand(payload, "bomb.zip"))

    def test_a_high_ratio_entry_is_refused(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.writestr("bomb.txt", "A" * (5 * 1024 * 1024))
        with pytest.raises(ArchiveRejectedError, match="compression ratio"):
            list(expand(buf.getvalue(), "bomb.zip"))

    def test_a_corrupt_archive_is_refused_not_crashed(self) -> None:
        with pytest.raises(ArchiveRejectedError, match="not a readable zip"):
            list(expand(b"this is not a zip file at all", "broken.zip"))

    def test_directories_are_skipped(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("folder/", "")
            z.writestr("folder/file.md", "# File\n")
        assert [m.path for m in expand(buf.getvalue(), "d.zip")] == ["folder/file.md"]


class TestIsArchive:
    @pytest.mark.parametrize(
        "name,expected",
        [("a.zip", True), ("A.ZIP", True), ("a.md", False), ("a.zip.md", False)],
    )
    def test_detection(self, name: str, expected: bool) -> None:
        assert is_archive(name) is expected
