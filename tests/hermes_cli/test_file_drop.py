from pathlib import Path

from hermes_cli.file_drop import (
    classify_dropped_file,
    format_link_token,
    parse_dragged_file_paste,
)


def test_classify_image_file(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    dropped = classify_dropped_file(img, tmp_path)
    assert dropped.kind == "image"


def test_classify_text_file_with_spaces_rejected(tmp_path):
    file_path = tmp_path / "my notes.py"
    file_path.write_text("print('x')\n")
    dropped = classify_dropped_file(file_path, tmp_path)
    assert dropped.kind == "invalid"
    assert dropped.reason == "spaces not supported in @path yet"


def test_format_link_token_prefers_relative_path(tmp_path):
    path = tmp_path / "src" / "main.py"
    path.parent.mkdir()
    path.write_text("print('x')\n")
    assert format_link_token(path, tmp_path) == "@src/main.py"


def test_format_link_token_falls_back_to_absolute_path(tmp_path):
    outside = Path("/tmp/hermes-file-drop-absolute.py")
    outside.write_text("print('x')\n")
    try:
        assert format_link_token(outside, tmp_path) == "@/tmp/hermes-file-drop-absolute.py"
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
