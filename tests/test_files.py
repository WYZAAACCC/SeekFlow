"""Tests for deepseek_toolkit.files — file attachment and text extraction."""
import base64
import tempfile
from pathlib import Path

import pytest

from deepseek_toolkit.files import (
    FileAttachment,
    embed_files_into_message,
    read_file_as_text,
    _format_file_block,
)


class TestReadFileAsText:
    """File reading and text extraction."""

    def test_read_text_file(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write("hello world")
            path = f.name
        try:
            result = read_file_as_text(path)
            assert result == "hello world"
        finally:
            Path(path).unlink()

    def test_read_python_file(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
            f.write("def add(a, b):\n    return a + b\n")
            path = f.name
        try:
            result = read_file_as_text(path)
            assert "def add" in result
        finally:
            Path(path).unlink()

    def test_read_json_file(self):
        content = '{"key": "value"}'
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False, encoding="utf-8") as f:
            f.write(content)
            path = f.name
        try:
            result = read_file_as_text(path)
            assert '"key"' in result
        finally:
            Path(path).unlink()

    def test_read_csv_file(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False, encoding="utf-8") as f:
            f.write("a,b,c\n1,2,3\n")
            path = f.name
        try:
            result = read_file_as_text(path)
            assert "a,b,c" in result
        finally:
            Path(path).unlink()

    def test_read_image_returns_base64(self):
        # Create a tiny valid PNG
        png_data = (
            b"\x89PNG\r\n\x1a\n"  # PNG signature
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        with tempfile.NamedTemporaryFile(suffix=".png", mode="wb", delete=False) as f:
            f.write(png_data)
            path = f.name
        try:
            result = read_file_as_text(path)
            assert "data:image/png;base64," in result
            assert "[Image:" in result
        finally:
            Path(path).unlink()

    def test_read_binary_file(self):
        data = b"\x00\x01\x02\xff\xfe\xfd"
        with tempfile.NamedTemporaryFile(suffix=".bin", mode="wb", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            result = read_file_as_text(path)
            assert "Binary file:" in result
            assert "base64:" in result
        finally:
            Path(path).unlink()


class TestEmbedFilesIntoMessage:
    """Embedding file content into messages."""

    def test_embeds_single_text_file(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write("file content here")
            path = f.name
        try:
            msg = {"role": "user", "content": "analyze this"}
            result = embed_files_into_message(msg, [path])
            assert "[file name]:" in result["content"]
            assert "[file content begin]" in result["content"]
            assert "file content here" in result["content"]
            assert "[file content end]" in result["content"]
            assert "analyze this" in result["content"]
        finally:
            Path(path).unlink()

    def test_embeds_multiple_files(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f1:
            f1.write("aaa")
            p1 = f1.name
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False, encoding="utf-8") as f2:
            f2.write("x,y\n1,2")
            p2 = f2.name
        try:
            msg = {"role": "user", "content": "compare these"}
            result = embed_files_into_message(msg, [p1, p2])
            assert "aaa" in result["content"]
            assert "x,y" in result["content"]
            assert result["content"].count("[file name]:") == 2
        finally:
            Path(p1).unlink()
            Path(p2).unlink()

    def test_no_files_returns_unchanged(self):
        msg = {"role": "user", "content": "hello"}
        result = embed_files_into_message(msg, [])
        assert result is msg  # same object returned
        assert result["content"] == "hello"

    def test_uses_fileattachment_object(self):
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, encoding="utf-8") as f:
            f.write("# Title\ncontent")
            path = f.name
        try:
            fa = FileAttachment(path, name="doc.md")
            msg = {"role": "user", "content": "summarize"}
            result = embed_files_into_message(msg, [fa])
            assert "[file name]: doc.md" in result["content"]
            assert "# Title" in result["content"]
        finally:
            Path(path).unlink()

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            embed_files_into_message(
                {"role": "user", "content": "x"},
                ["/nonexistent/file.txt"],
            )


class TestFormatFileBlock:
    """DeepSeek template formatting."""

    def test_format_file_block(self):
        block = _format_file_block("test.py", "print('hello')")
        assert block == (
            "[file name]: test.py\n"
            "[file content begin]\n"
            "print('hello')\n"
            "[file content end]"
        )

    def test_format_file_block_multiline(self):
        block = _format_file_block("data.csv", "a,b\n1,2\n3,4")
        assert "[file content begin]" in block
        assert "a,b" in block
        assert "[file content end]" in block
