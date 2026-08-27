"""Transcript ingestion: an oversized URL fetch must FAIL, never silently truncate
(a truncated transcript analysed as if whole would corrupt every downstream check)."""
import pytest

from earnings import ingest


class _FakeResp:
    def __init__(self, content: bytes):
        self.content = content
        self.headers = {"content-type": "text/plain"}
        self.encoding = "utf-8"

    def raise_for_status(self):
        return None


class _FakeClient:
    def __init__(self, content: bytes):
        self._content = content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url):
        return _FakeResp(self._content)


def test_fetch_url_rejects_oversized_transcript(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_FETCH_BYTES", 10)
    monkeypatch.setattr(ingest.httpx, "Client", lambda **kw: _FakeClient(b"x" * 50))
    with pytest.raises(ValueError, match="Refusing to analyse a truncated transcript"):
        ingest.fetch_url("https://example.com/big")


def test_fetch_url_accepts_within_cap(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_FETCH_BYTES", 100)
    monkeypatch.setattr(ingest.httpx, "Client", lambda **kw: _FakeClient(b"hello world"))
    loaded = ingest.fetch_url("https://example.com/ok")
    assert loaded.raw_text == "hello world"
    assert loaded.origin == "https://example.com/ok"
