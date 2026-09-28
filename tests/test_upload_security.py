import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ["ADR_DB_PATH"] = "/tmp/adr_upload_test.db"
os.environ["ADR_CONFIG_PATH"] = "/tmp/adr_upload_config.json"

import pytest
from app.ingestion import sanitize_filename, validate_upload


def test_filename_is_sanitized():
    assert sanitize_filename("../../secret document?.txt") == "secret_document_.txt"


def test_magic_bytes_are_checked(tmp_path: Path):
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        validate_upload("fake.pdf", fake_pdf.stat().st_size, str(fake_pdf))


def test_text_upload_is_accepted(tmp_path: Path):
    text = tmp_path / "safe.txt"
    text.write_text("Section 1: safe", encoding="utf-8")
    assert validate_upload("safe.txt", text.stat().st_size, str(text)) == ".txt"
