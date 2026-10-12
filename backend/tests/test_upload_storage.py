from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.storage import LocalPrivateStorage
from app.services.upload_validation import read_pdf_content


def test_storage_uses_opaque_names_and_blocks_path_escape(tmp_path: Path):
    storage = LocalPrivateStorage(str(tmp_path))
    stored = storage.save("session-a", b"%PDF-1.7 test")

    assert stored.endswith(".pdf")
    assert stored != "paper.pdf"
    assert storage.resolve("session-a", stored).read_bytes().startswith(b"%PDF-")

    with pytest.raises(ValueError):
        storage.resolve("session-a", "../outside.pdf")


def test_upload_validation_requires_pdf_magic_bytes_and_size():
    assert read_pdf_content(b"%PDF-1.7 body") == b"%PDF-1.7 body"

    with pytest.raises(HTTPException) as invalid:
        read_pdf_content(b"not a pdf")
    assert invalid.value.status_code == 400
