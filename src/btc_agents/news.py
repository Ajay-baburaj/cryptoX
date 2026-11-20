"""Keyless news polling and a point-in-time headline archive."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
import sqlite3
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

import pandas as pd
import requests

FEEDS = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph_btc": "https://cointelegraph.com/rss/tag/bitcoin",
    "fed": "https://www.federalreserve.gov/feeds/press_monetary.xml",
    "bls_cpi": "https://www.bls.gov/feed/cpi.rss",
    "bls_jobs": "https://www.bls.gov/feed/empsit.rss",
}
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
BTC = re.compile(r"\b(bitcoin|btc|xbt)\b", re.I)
TOPICS = {
    "macro_release": re.compile(r"monetary policy|federal open market|employment situation|consumer price index|\b(fomc|cpi|payrolls)\b", re.I),
    "security_event": re.compile(r"\b(hack(?:ed)?|exploit(?:ed)?|breach|outage)\b", re.I),
    "fund_flow": re.compile(r"\b(etfs?|inflows?|outflows?)\b", re.I),
    "regulation": re.compile(r"\b(regulation|sec|ban|lawsuit|approval)\b", re.I),
}


def timestamp(value):
    if not value:
        return None
    try:
        parsed = pd.Timestamp(value)
        if not pd.isna(parsed) and parsed.tzinfo is not None:
            return parsed.tz_convert("UTC")
    except (TypeError, ValueError):
        pass
    try:
        parsed = parsedate_to_datetime(value)
        return pd.Timestamp(parsed).tz_convert("UTC") if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def canonical_url(url):
    parts = urlsplit(url.strip())
    if parts.scheme not in ("https", "http") or not parts.hostname:
        return ""
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"ref", "fbclid", "gclid"}]
    return urlunsplit(("https", parts.netloc.lower().removeprefix("www."), parts.path or "/", urlencode(sorted(query)), ""))


def parse_feed(content):
    root = ElementTree.fromstring(content)
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] not in {"item", "entry"}:
            continue
        fields = {}
        for child in element:
            key = child.tag.rsplit("}", 1)[-1]
            if key == "link" and child.attrib.get("rel", "alternate") != "alternate":
                continue
            fields[key] = child.attrib.get("href", child.text or "")
        date = fields.get("pubDate") or fields.get("published") or fields.get("date")
        yield fields.get("title", ""), fields.get("link", ""), timestamp(date)


def parse_gdelt(response):
    for item in response.get("articles", []):
        # seendate is GDELT's observation time, not a publisher timestamp.
        yield item.get("title", ""), item.get("url", ""), None


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.execute("""CREATE TABLE IF NOT EXISTS headlines (
        url TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL,
        published_at TEXT, first_seen_at TEXT NOT NULL, available_at TEXT NOT NULL,
        topic TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS headline_time ON headlines(available_at)")
    return db


def store(db, source, articles, seen):
    before = db.total_changes
    with db:
        for title, link, published in articles:
            title = " ".join(title.split())
            url = canonical_url(link)
            if not title or not url:
                continue
            topic = next((name for name, pattern in TOPICS.items() if pattern.search(title)), "general")
            if source in {"bls_cpi", "bls_jobs"}:
                topic = "macro_release"
            if not (BTC.search(title) or source in {"fed", "bls_cpi", "bls_jobs"}):
                continue
            available = max(seen, published) if published is not None else seen
            db.execute("INSERT OR IGNORE INTO headlines VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (url, source, title, published.isoformat() if published is not None else None,
                        seen.isoformat(), available.isoformat(), topic))
    return db.total_changes - before


def poll(path, sources, query="bitcoin sourcelang:english"):
    outcome = {}
    with requests.Session() as session:
        session.headers["User-Agent"] = "CryptoX-BTC-Research/1.0 (RSS and public market research)"
        db = connect(path)
        try:
            for source in sources:
                try:
                    gdelt = source == "gdelt"
                    params = ({"query": query, "mode": "artlist", "format": "json",
                               "timespan": "24h", "sort": "datedesc", "maxrecords": 75} if gdelt else None)
                    response = session.get(GDELT_URL if gdelt else FEEDS[source], params=params, timeout=15)
                    response.raise_for_status()
                    articles = list(parse_gdelt(response.json()) if gdelt else parse_feed(response.content))
                    now = pd.Timestamp(datetime.now(timezone.utc))
                    outcome[source] = {"received": len(articles), "stored": store(db, source, articles, now)}
                except (requests.RequestException, ValueError, ElementTree.ParseError) as error:
                    outcome[source] = {"error": str(error)}
        finally:
            db.close()
    return outcome


def load(path):
    if not path or not Path(path).is_file():
        return pd.DataFrame(columns=["available_at", "published_at", "topic", "title"])
    db = connect(path)
    try:
        frame = pd.read_sql_query("SELECT * FROM headlines ORDER BY available_at", db)
    finally:
        db.close()
    for col in ("available_at", "published_at"):
        frame[col] = pd.to_datetime(frame[col], utc=True, format="mixed")
    return frame
