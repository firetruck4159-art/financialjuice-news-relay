#!/usr/bin/env python3
"""Publish a small FinancialJuice snapshot from the existing Cloudflare relay."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DATA_PATH = Path(os.environ.get("NEWS_JSON_PATH", "news.json"))
RELAY_URL = os.environ.get(
    "RELAY_URL",
    "https://financialjuice-rss-relay.firetruck4159.workers.dev/?limit=50",
)
MAX_ITEMS = 150
KEEP_HOURS = 12

def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def read_existing() -> dict:
    if not DATA_PATH.exists():
        return {}
    try:
        val = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        return val if isinstance(val, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

def parse_pub_date(value: str) -> datetime:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid pubDate") from exc
    if parsed.tzinfo is None:
        raise ValueError("pubDate lacks timezone")
    return parsed.astimezone(timezone.utc)

def clean_record(item: dict) -> dict:
    if not isinstance(item, dict):
        raise ValueError("item must be a JSON object")
    for field in ("guid", "title", "link", "pubDate"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            raise ValueError(f"missing/invalid field: {field}")
    link = item["link"].strip()
    if urlparse(link).scheme not in ("http", "https") or not urlparse(link).netloc:
        raise ValueError("invalid article link")
    published = parse_pub_date(item["pubDate"])
    description = item.get("description")
    description = description if isinstance(description, str) else ""
    return {
        "guid": item["guid"].strip()[:500],
        "title": item["title"].strip()[:350],
        "link": link,
        "pubDate": item["pubDate"].strip(),
        "publishedAt": iso_utc(published),
        "description": description.strip()[:360],
    }

def fetch_relay(url: str) -> list[dict]:
    parts = urlparse(url)
    if parts.scheme != "https" or not parts.netloc:
        raise RuntimeError("RELAY_URL must be HTTPS")
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "FinancialJuice-JSON-Relay/1.0"})
    with urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"upstream returned HTTP {response.status}")
        blob = response.read(512 * 1024 + 1)
        if len(blob) > 512 * 1024:
            raise RuntimeError("relay response exceeds 512 KiB")
    try:
        payload = json.loads(blob.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("relay response was not valid JSON") from exc
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("relay must return a non-empty JSON array")
    return payload

def build_snapshot(previous: dict, raw_items: list[dict], current: datetime) -> dict:
    validated = [clean_record(item) for item in raw_items]
    by_guid: dict[str, dict] = {}
    for item in previous.get("articles", []):
        if isinstance(item, dict):
            try:
                clean = clean_record(item)
                by_guid[clean["guid"]] = clean
            except ValueError:
                continue
    for item in validated:
        by_guid[item["guid"]] = item
    cutoff = current - timedelta(hours=KEEP_HOURS)
    retained = [
        x for x in sorted(by_guid.values(), key=lambda x: x["publishedAt"], reverse=True)
        if parse_pub_date(x["publishedAt"]) >= cutoff
    ][:MAX_ITEMS]
    return {
        "schemaVersion": 1,
        "source": "FinancialJuice RSS via existing Cloudflare Worker",
        "status": "ok",
        "lastAttemptAt": iso_utc(current),
        "lastSuccessAt": iso_utc(current),
        "sourceNewestAt": max((x["publishedAt"] for x in validated), default=None),
        "upstreamItemCount": len(raw_items),
        "retentionHours": KEEP_HOURS,
        "articleCount": len(retained),
        "lastError": None,
        "articles": retained,
    }

def build_failure(previous: dict, current: datetime, message: str) -> dict:
    return {
        "schemaVersion": 1,
        "source": "FinancialJuice RSS via existing Cloudflare Worker",
        "status": "error",
        "lastAttemptAt": iso_utc(current),
        "lastSuccessAt": previous.get("lastSuccessAt"),
        "sourceNewestAt": previous.get("sourceNewestAt"),
        "upstreamItemCount": None,
        "retentionHours": KEEP_HOURS,
        "articleCount": len(previous.get("articles", [])),
        "lastError": message[:240],
        "articles": previous.get("articles", []),
    }

def run() -> int:
    current = datetime.now(timezone.utc)
    previous = read_existing()
    try:
        items = fetch_relay(RELAY_URL)
        snapshot = build_snapshot(previous, items, current)
        result = 0
        print(f"OK: fetched {len(items)} source items, retained {snapshot['articleCount']}")
    except Exception as exc:
        safe = type(exc).__name__
        if isinstance(exc, (RuntimeError, ValueError)):
            safe = f"{type(exc).__name__}: {str(exc)[:150]}"
        snapshot = build_failure(previous, current, safe)
        result = 1
        print(f"ERROR: {safe}", file=sys.stderr)
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result

if __name__ == "__main__":
    raise SystemExit(run())
