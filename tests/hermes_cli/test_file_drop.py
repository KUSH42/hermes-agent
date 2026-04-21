from pathlib import Path

from hermes_cli.file_drop import (
    _MAX_FILE_DROP_CHARS,
    _MAX_FILE_DROP_LINES,
    classify_dropped_file,
    format_link_token,
    parse_dragged_file_paste,
)


def test_classify_image_file(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    dropped = classify_dropped_file(img, tmp_path)
    assert dropped.kind == "image"


def test_classify_text_file_with_spaces_accepted(tmp_path):
    file_path = tmp_path / "my notes.py"
    file_path.write_text("print('x')\n")
    dropped = classify_dropped_file(file_path, tmp_path)
    assert dropped.kind == "linkable_text"


def test_format_link_token_quotes_spaces(tmp_path):
    path = tmp_path / "my notes.py"
    path.write_text("print('x')\n")
    token = format_link_token(path, tmp_path)
    assert token == '"my notes.py"'


def test_format_link_token_prefers_relative_path(tmp_path):
    path = tmp_path / "src" / "main.py"
    path.parent.mkdir()
    path.write_text("print('x')\n")
    assert format_link_token(path, tmp_path) == "src/main.py"


def test_format_link_token_falls_back_to_absolute_path(tmp_path):
    outside = Path("/tmp/hermes-file-drop-absolute.py")
    outside.write_text("print('x')\n")
    try:
        assert format_link_token(outside, tmp_path) == "/tmp/hermes-file-drop-absolute.py"
    finally:
        outside.unlink(missing_ok=True)


def test_parse_dragged_file_paste_supports_newlines_and_file_uri(tmp_path):
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("a\n")
    b.write_text("b\n")
    payload = f"{a.as_uri()}\n{b}"
    parsed = parse_dragged_file_paste(payload)
    assert parsed == [a, b]


def test_parse_dragged_file_paste_rejects_mixed_text(tmp_path):
    a = tmp_path / "a.py"
    a.write_text("a\n")
    assert parse_dragged_file_paste(f"{a} please review") is None


def test_parse_dragged_file_paste_rejects_long_text():
    """Pasting multi-KB prose must bail out immediately without stat() calls."""
    long_text = "a]line of prose\n" * 300  # ~4800 chars, well over 4096
    assert parse_dragged_file_paste(long_text) is None


def test_parse_dragged_file_paste_rejects_many_lines(tmp_path):
    """More than _MAX_FILE_DROP_LINES lines is clearly prose, not a file drop."""
    # Create valid files but exceed the line limit
    lines = []
    for i in range(_MAX_FILE_DROP_LINES + 1):
        p = tmp_path / f"f{i}.py"
        p.write_text("x\n")
        lines.append(str(p))
    assert parse_dragged_file_paste("\n".join(lines)) is None


def test_parse_dragged_file_paste_accepts_up_to_limit(tmp_path):
    """Exactly _MAX_FILE_DROP_LINES existing files should still parse."""
    lines = []
    for i in range(_MAX_FILE_DROP_LINES):
        p = tmp_path / f"f{i}.py"
        p.write_text("x\n")
        lines.append(str(p))
    result = parse_dragged_file_paste("\n".join(lines))
    assert result is not None
    assert len(result) == _MAX_FILE_DROP_LINES


def test_parse_dragged_file_paste_strips_quotes(tmp_path):
    path = tmp_path / "test.py"
    path.write_text("x=1\n")
    # Double-quoted
    assert parse_dragged_file_paste(f'"{path}"') == [path]
    # Single-quoted
    assert parse_dragged_file_paste(f"'{path}'") == [path]


def test_parse_dragged_file_paste_accepts_path_with_spaces(tmp_path):
    path = tmp_path / "my file.py"
    path.write_text("x=1\n")
    assert parse_dragged_file_paste(str(path)) == [path]
    assert parse_dragged_file_paste(f'"{path}"') == [path]


def test_parse_dragged_file_paste_multi_file_space_separated(tmp_path):
    a = tmp_path / "a.py"
    b = tmp_path / "b.txt"
    a.write_text("x\n")
    b.write_text("y\n")
    result = parse_dragged_file_paste(f"{a} {b}")
    assert result == [a, b]


def test_parse_dragged_file_paste_multi_file_mixed_quotes(tmp_path):
    a = tmp_path / "a.py"
    b = tmp_path / "with spaces.txt"
    c = tmp_path / "c.md"
    a.write_text("x\n")
    b.write_text("y\n")
    c.write_text("z\n")
    result = parse_dragged_file_paste(f'{a} "{b}" {c}')
    assert result == [a, b, c]
