from pathlib import Path

import pytest

from blue_data_user_source.sources.file import FileSource


@pytest.fixture
def txt_file(tmp_path: Path) -> Path:
    f = tmp_path / "resume.txt"
    f.write_text("Python\nSQL\nMachine learning\n")
    return f


async def test_query_returns_file_lines(txt_file: Path) -> None:
    source = FileSource(txt_file)
    result = await source.query("What skills?")
    assert result == ["Python", "SQL", "Machine learning"]


async def test_query_ignores_query_argument(txt_file: Path) -> None:
    source = FileSource(txt_file)
    assert await source.query("anything") == await source.query("something else")


async def test_source_type_is_file(txt_file: Path) -> None:
    assert FileSource(txt_file).source_type == "file"


async def test_location_is_string_path(txt_file: Path) -> None:
    source = FileSource(txt_file)
    assert source.location == str(txt_file)


async def test_accepts_string_path(tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_text("line1\n")
    source = FileSource(str(f))
    result = await source.query("")
    assert result == ["line1"]


async def test_empty_file_returns_empty_list(tmp_path: Path) -> None:
    f = tmp_path / "empty.txt"
    f.write_text("")
    source = FileSource(f)
    assert await source.query("") == []


async def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    source = FileSource(tmp_path / "missing.txt")
    with pytest.raises(FileNotFoundError):
        await source.query("")
