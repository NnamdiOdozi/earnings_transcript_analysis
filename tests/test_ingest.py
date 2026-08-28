"""Transcript ingestion: an oversized URL fetch must FAIL, never silently truncate
(a truncated transcript analysed as if whole would corrupt every downstream check).
Also covers PDF ingestion (local file and URL) via a monkeypatched pypdf extractor --
we don't construct real PDF byte streams in these tests, just verify the wiring."""
import pytest

from earnings import ingest


class _FakeResp:
    def __init__(self, content: bytes, content_type: str = "text/plain"):
        self.content = content
        self.headers = {"content-type": content_type}
        self.encoding = "utf-8"

    def raise_for_status(self):
        return None


class _FakeClient:
    def __init__(self, content: bytes, content_type: str = "text/plain"):
        self._content = content
        self._content_type = content_type

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url):
        return _FakeResp(self._content, self._content_type)


def test_fetch_url_rejects_oversized_transcript(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_FETCH_BYTES", 10)
    monkeypatch.setattr(ingest.httpx, "Client", lambda **kw: _FakeClient(b"x" * 50))
    with pytest.raises(ValueError, match="Refusing to analyse a truncated transcript"):
        ingest.fetch_url("https://example.com/big")


def test_fetch_url_rejects_oversized_pdf(monkeypatch):
    """The size cap must apply to raw PDF bytes too, before any PDF conversion."""
    monkeypatch.setattr(ingest, "MAX_FETCH_BYTES", 10)
    monkeypatch.setattr(ingest.httpx, "Client", lambda **kw: _FakeClient(b"x" * 50, "application/pdf"))
    with pytest.raises(ValueError, match="Refusing to analyse a truncated transcript"):
        ingest.fetch_url("https://example.com/big.pdf")


def test_fetch_url_accepts_within_cap(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_FETCH_BYTES", 100)
    monkeypatch.setattr(ingest.httpx, "Client", lambda **kw: _FakeClient(b"hello world"))
    loaded = ingest.fetch_url("https://example.com/ok")
    assert loaded.raw_text == "hello world"
    assert loaded.origin == "https://example.com/ok"
    assert loaded.raw_bytes is None
    assert loaded.raw_suffix is None


def test_fetch_url_detects_pdf_via_content_type(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_FETCH_BYTES", 1000)
    monkeypatch.setattr(ingest, "_extract_pdf_text", lambda data: "extracted pdf text")
    monkeypatch.setattr(ingest.httpx, "Client", lambda **kw: _FakeClient(b"%PDF-fake-bytes", "application/pdf"))
    loaded = ingest.fetch_url("https://example.com/transcript")
    assert loaded.raw_text == "extracted pdf text"
    assert loaded.is_html is False
    assert loaded.content_type == "text/markdown"
    assert loaded.raw_bytes == b"%PDF-fake-bytes"
    assert loaded.raw_suffix == ".pdf"


def test_fetch_url_detects_pdf_via_url_suffix(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_FETCH_BYTES", 1000)
    monkeypatch.setattr(ingest, "_extract_pdf_text", lambda data: "extracted pdf text")
    monkeypatch.setattr(ingest.httpx, "Client", lambda **kw: _FakeClient(b"%PDF-fake-bytes", "text/plain"))
    loaded = ingest.fetch_url("https://example.com/transcript.pdf")
    assert loaded.raw_text == "extracted pdf text"
    assert loaded.raw_bytes == b"%PDF-fake-bytes"
    assert loaded.raw_suffix == ".pdf"


def test_load_local_file_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "_extract_pdf_text", lambda data: "extracted pdf text")
    pdf_path = tmp_path / "transcript.pdf"
    data = b"%PDF-fake-bytes"
    pdf_path.write_bytes(data)
    loaded = ingest.load_local_file(pdf_path)
    assert loaded.raw_text == "extracted pdf text"
    assert loaded.is_html is False
    assert loaded.content_type == "text/markdown"
    assert loaded.raw_bytes == data
    assert loaded.raw_suffix == ".pdf"


def test_load_local_file_unsupported_suffix(tmp_path):
    bad_path = tmp_path / "transcript.docx"
    bad_path.write_text("hello")
    with pytest.raises(ValueError, match="expected txt/md/html/pdf"):
        ingest.load_local_file(bad_path)
