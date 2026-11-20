"""Published daily US spot BTC ETF flows and Bitcoin sentiment."""
from datetime import datetime, timezone
from html import unescape
import re

import requests


def latest_flow(html):
    if "Bitcoin ETF Flow" not in html or "US$m" not in html:
        raise ValueError("Unexpected ETF flow table")
    complete = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, re.I | re.S):
        cells = [unescape(re.sub("<[^>]+>", "", cell)).strip() for cell in
                 re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.I | re.S)]
        if len(cells) < 4 or not re.fullmatch(r"\d{1,2} [A-Za-z]{3} \d{4}", cells[0]):
            continue
        if not all(re.fullmatch(r"(?:\([\d,.]+\)|-?[\d,.]+)", v) for v in cells[1:]):
            continue
        total = cells[-1].replace(",", "").replace("(", "-").replace(")", "")
        complete.append((datetime.strptime(cells[0], "%d %b %Y").date(), float(total)*1_000_000))
    if not complete:
        raise ValueError("No fully reported ETF day")
    return max(complete)


def daily_context(session):
    observations, errors = [], {}
    now = datetime.now(timezone.utc)
    for metric, source, url in (
        ("fear_greed", "Alternative.me", "https://api.alternative.me/fng/?limit=1"),
        ("etf_net_flow_usd", "Farside", "https://farside.co.uk/btc/"),
    ):
        try:
            response = session.get(url, timeout=12)
            response.raise_for_status()
            if metric == "fear_greed":
                item = response.json()["data"][0]
                day = datetime.fromtimestamp(int(item["timestamp"]), timezone.utc).date()
                value = int(item["value"])
                if not 0 <= value <= 100:
                    raise ValueError("Invalid sentiment value")
            else:
                day, value = latest_flow(response.text)
            if not 0 <= (now.date() - day).days <= (4 if metric == "etf_net_flow_usd" else 1):
                raise ValueError("Provider observation is stale")
            observations.append(dict(available_at=datetime.now(timezone.utc).isoformat(), metric=metric,
                                     value=value, source=f"{source} {day.isoformat()}"))
        except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as error:
            errors[source] = str(error)
    return observations, errors
