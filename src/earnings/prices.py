"""Price-series lookups: Yahoo Finance (default), Financial Modeling Prep, Alpha
Vantage.

Yahoo Finance (via the `yfinance` package -- Yahoo has no official public REST
API, so there's no raw-httpx equivalent to call the way sources.py calls
Tavily/Exa/SEC) is free and needs no API key, so it's the default for a plain
price query. FMP and Alpha Vantage are thin httpx wrappers, same pattern as
sources.py's other providers -- reach for them specifically when Yahoo has no
data for a symbol, or for the additional fundamentals data those two APIs offer
beyond prices (not implemented here, prices only).

Available for an agent to call directly (e.g. from a Python REPL or a one-off
script) when it needs a price series to fill a gap or cross-check a claim; not
wired into the `earnings prepare`/`analyze` pipeline, so the caller decides
when to use it.

Env vars (exact names as configured in .env; Yahoo needs none):
FMDP_API_KEY (Financial Modeling Prep), ALPHA_VANTAGE_API_KEY (Alpha Vantage).

Every call is logged -- request (params, API key redacted) and response (status,
row count, date range, a hash of the raw body, and the rows themselves) -- to
logs/price_lookups.jsonl (cross-run, always) and additionally to
<run_dir>/price_lookups.jsonl when the caller passes `run_dir` (an agent working
inside a specific ticker/event run should pass it so the lookup becomes part of
that run's own audit trail, same as everything else this pipeline archives).
Logging happens on failure too -- a raised exception is still recorded before
it propagates, so a missing key or a bad HTTP response is not silently unlogged.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yfinance

from .config import LOGS_DIR, PRICE_LOOKUP_LOG_FILENAME

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
HTTP_TIMEOUT_SECONDS = 20.0


def fmp_api_key() -> str | None:
    return os.environ.get("FMDP_API_KEY")


def alpha_vantage_api_key() -> str | None:
    return os.environ.get("ALPHA_VANTAGE_API_KEY")


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_price_lookup(
    provider: str,
    ticker: str,
    request: dict[str, Any],
    *,
    status: str,
    http_status: int | None,
    raw_body: bytes | None,
    rows: list[dict[str, Any]] | None,
    error: str | None,
    run_dir: Path | None,
) -> None:
    """Append one JSONL entry recording this call, cross-run and (if given) per-run.

    `request` must already have any API key redacted by the caller. `status` is
    "ok" or "error"; on error, `rows`/`raw_body` may be partial or None.
    """
    entry = {
        "timestamp": _now_iso(),
        "provider": provider,
        "ticker": ticker.upper(),
        "request": request,
        "status": status,
        "http_status": http_status,
        "error": error,
        "row_count": len(rows) if rows else 0,
        "date_range": {"first": rows[0]["date"], "last": rows[-1]["date"]} if rows else None,
        "response_sha256": hashlib.sha256(raw_body).hexdigest() if raw_body else None,
        "rows": rows,
    }
    line = json.dumps(entry) + "\n"

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with (LOGS_DIR / PRICE_LOOKUP_LOG_FILENAME).open("a", encoding="utf-8") as fh:
        fh.write(line)

    if run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        with (run_dir / PRICE_LOOKUP_LOG_FILENAME).open("a", encoding="utf-8") as fh:
            fh.write(line)


def get_price_series_yahoo(
    ticker: str, period: str = "1y", *, run_dir: Path | None = None
) -> list[dict[str, Any]]:
    """Daily OHLCV price series for `ticker` from Yahoo Finance, via `yfinance`.
    `period` is a yfinance period string: "1mo", "3mo", "6mo", "1y", "2y", "5y",
    "10y", "ytd", or "max".

    Free, no API key required -- this is the DEFAULT price lookup for a plain
    price query; reach for get_price_series_fmp/get_price_series_alpha_vantage
    instead when Yahoo has no data for the symbol, or you need fundamentals data
    those providers offer beyond price.

    Returns a list of {date, open, high, low, close, volume} dicts, oldest first.
    Raises RuntimeError if Yahoo returns no data (invalid ticker, delisted, etc.)
    or the lookup otherwise fails.
    """
    request = {"endpoint": "yfinance.Ticker.history", "params": {"period": period}}
    try:
        hist = yfinance.Ticker(ticker).history(period=period)
    except Exception as exc:  # yfinance surfaces a mix of requests/internal errors
        _log_price_lookup(
            "yahoo", ticker, request, status="error", http_status=None, raw_body=None,
            rows=None, error=str(exc), run_dir=run_dir,
        )
        raise RuntimeError(f"Yahoo Finance lookup failed for {ticker}: {exc}") from exc

    if hist.empty:
        _log_price_lookup(
            "yahoo", ticker, request, status="error", http_status=None, raw_body=None,
            rows=None, error="no data returned", run_dir=run_dir,
        )
        raise RuntimeError(f"Yahoo Finance returned no data for {ticker!r} (invalid ticker, delisted, or no history)")

    rows = [
        {
            "date": idx.strftime("%Y-%m-%d"),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        }
        for idx, row in hist.iterrows()
    ]
    # yfinance wraps its own HTTP calls internally -- no raw response body/status
    # code is exposed the way httpx gives us for FMP/Alpha Vantage below, so the
    # logged hash covers the parsed rows instead of a raw HTTP body.
    _log_price_lookup(
        "yahoo", ticker, request, status="ok", http_status=None,
        raw_body=json.dumps(rows, sort_keys=True).encode("utf-8"),
        rows=rows, error=None, run_dir=run_dir,
    )
    return rows


def get_price_series(ticker: str, *, run_dir: Path | None = None) -> list[dict[str, Any]]:
    """Default price-series lookup -- Yahoo Finance (free, no API key). Convenience
    alias for get_price_series_yahoo(ticker, run_dir=run_dir); call
    get_price_series_fmp/get_price_series_alpha_vantage directly when you
    specifically need one of those providers instead.
    """
    return get_price_series_yahoo(ticker, run_dir=run_dir)


def get_price_series_fmp(
    ticker: str, days: int = 365, *, run_dir: Path | None = None
) -> list[dict[str, Any]]:
    """Daily OHLCV price series for `ticker` from Financial Modeling Prep's
    "historical-price-full" endpoint, most recent `days` calendar days.

    Returns a list of {date, open, high, low, close, volume} dicts, oldest first.
    Raises RuntimeError if fmdp_API_KEY is not set. Pass `run_dir` (a specific
    ticker/event run directory) to also log this call into that run's own
    price_lookups.jsonl, not just the cross-run log.
    """
    api_key = fmp_api_key()
    request = {"endpoint": f"historical-price-full/{ticker}", "params": {"timeseries": days}}
    if not api_key:
        _log_price_lookup(
            "fmp", ticker, request, status="error", http_status=None, raw_body=None,
            rows=None, error="fmdp_API_KEY is not set", run_dir=run_dir,
        )
        raise RuntimeError("fmdp_API_KEY is not set; cannot fetch FMP price series")

    try:
        resp = httpx.get(
            f"{FMP_BASE_URL}/historical-price-full/{ticker}",
            params={"apikey": api_key, "timeseries": days},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        _log_price_lookup(
            "fmp", ticker, request, status="error",
            http_status=getattr(getattr(exc, "response", None), "status_code", None),
            raw_body=getattr(getattr(exc, "response", None), "content", None),
            rows=None, error=str(exc), run_dir=run_dir,
        )
        raise

    rows = sorted(
        (
            {
                "date": row["date"],
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
            }
            for row in data.get("historical", [])
        ),
        key=lambda r: r["date"],
    )
    _log_price_lookup(
        "fmp", ticker, request, status="ok", http_status=resp.status_code,
        raw_body=resp.content, rows=rows, error=None, run_dir=run_dir,
    )
    return rows


def get_price_series_alpha_vantage(
    ticker: str, compact: bool = True, *, run_dir: Path | None = None
) -> list[dict[str, Any]]:
    """Daily OHLCV price series for `ticker` from Alpha Vantage's
    TIME_SERIES_DAILY function. `compact` (default) returns the latest ~100
    trading days; set False for the full available history.

    Returns a list of {date, open, high, low, close, volume} dicts, oldest first.
    Raises RuntimeError if alpha_vantage_API_KEY is not set. Pass `run_dir` (a
    specific ticker/event run directory) to also log this call into that run's
    own price_lookups.jsonl, not just the cross-run log.
    """
    api_key = alpha_vantage_api_key()
    request = {
        "endpoint": "TIME_SERIES_DAILY",
        "params": {"symbol": ticker, "outputsize": "compact" if compact else "full"},
    }
    if not api_key:
        _log_price_lookup(
            "alpha_vantage", ticker, request, status="error", http_status=None,
            raw_body=None, rows=None, error="alpha_vantage_API_KEY is not set", run_dir=run_dir,
        )
        raise RuntimeError("alpha_vantage_API_KEY is not set; cannot fetch Alpha Vantage price series")

    try:
        resp = httpx.get(
            ALPHA_VANTAGE_URL,
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": ticker,
                "outputsize": "compact" if compact else "full",
                "apikey": api_key,
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        _log_price_lookup(
            "alpha_vantage", ticker, request, status="error",
            http_status=getattr(getattr(exc, "response", None), "status_code", None),
            raw_body=getattr(getattr(exc, "response", None), "content", None),
            rows=None, error=str(exc), run_dir=run_dir,
        )
        raise

    series = data.get("Time Series (Daily)", {})
    rows = sorted(
        (
            {
                "date": date_str,
                "open": float(row["1. open"]),
                "high": float(row["2. high"]),
                "low": float(row["3. low"]),
                "close": float(row["4. close"]),
                "volume": int(row["5. volume"]),
            }
            for date_str, row in series.items()
        ),
        key=lambda r: r["date"],
    )
    # Alpha Vantage returns HTTP 200 even on a bad symbol/rate-limit -- the error
    # shows up as an "Error Message"/"Note" key with no "Time Series (Daily)".
    # Log it as an error, not a silent zero-row "ok", so it's not mistaken for a
    # genuinely empty series.
    if not series and ("Error Message" in data or "Note" in data or "Information" in data):
        api_error = data.get("Error Message") or data.get("Note") or data.get("Information")
        _log_price_lookup(
            "alpha_vantage", ticker, request, status="error", http_status=resp.status_code,
            raw_body=resp.content, rows=None, error=api_error, run_dir=run_dir,
        )
        raise RuntimeError(f"Alpha Vantage error for {ticker}: {api_error}")

    _log_price_lookup(
        "alpha_vantage", ticker, request, status="ok", http_status=resp.status_code,
        raw_body=resp.content, rows=rows, error=None, run_dir=run_dir,
    )
    return rows
