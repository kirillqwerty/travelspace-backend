import asyncio
from io import BytesIO

import pytest
from PIL import Image
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers
import server


def upload(content, name="photo.jpg", content_type="image/jpeg"):
    return UploadFile(file=BytesIO(content), filename=name, headers=Headers({"content-type": content_type}))


@pytest.mark.parametrize("format,extension", [("PNG", ".png"), ("JPEG", ".jpg"), ("WEBP", ".webp")])
def test_upload_detects_real_format_and_round_trips_bytes(monkeypatch, tmp_path, format, extension):
    monkeypatch.setattr(server, "UPLOAD_DIR", tmp_path)
    output = BytesIO()
    Image.new("RGB", (20, 10), "orange").save(output, format=format)
    result = asyncio.run(server.admin_upload_file(upload(output.getvalue()), current={"role": "admin"}))
    assert result["url"].endswith(extension)
    assert (tmp_path / result["url"].split("/")[-1]).read_bytes() == output.getvalue()


@pytest.mark.parametrize("content,mime,status", [(b"", "image/png", 400), (b"not an image", "image/jpeg", 400), (b"text", "text/plain", 400), (b"x" * (2 * 1024 * 1024 + 1), "image/png", 413)], ids=["empty", "corrupt", "wrong-type", "oversize"])
def test_invalid_upload_does_not_create_a_file(monkeypatch, tmp_path, content, mime, status):
    monkeypatch.setattr(server, "UPLOAD_DIR", tmp_path)
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.admin_upload_file(upload(content, content_type=mime), current={"role": "admin"}))
    assert error.value.status_code == status
    assert not list(tmp_path.iterdir())
