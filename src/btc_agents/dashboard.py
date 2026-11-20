"""Minute-updated agent observations for the dashboard."""
import pandas as pd

from . import agents
from .features import TIMEFRAMES, complete_bars, indicators

TIERS = (("4h", "h4"), ("1h", "h1"), ("15m", "m15"), ("5m", "m5"))
METRICS = {
    "4h": ("close", "ema50", "adx", "atr_pct"),
    "1h": ("close", "zone_support_high", "zone_resistance_low", "momentum"),
    "15m": ("close", "ema20", "rsi", "macd_hist"),
    "5m": ("close", "range_low", "range_high", "rvol"),
}


def preview(minutes, confirmed):
    observed = minutes.index[-1] + pd.Timedelta(minutes=1)
    row = confirmed.copy()
    row.name = observed
    for tf, prefix in TIERS:
        size = TIMEFRAMES[tf]
        step = pd.Timedelta(minutes=size)
        start = observed.floor(f"{size}min")
        if start == observed:
            continue
        part = minutes.loc[start:]
        bars = complete_bars(minutes.loc[minutes.index < start], tf)
        if len(part) != (observed - start) // pd.Timedelta(minutes=1):
            for key in row.index[row.index.str.startswith(prefix + "_")]:
                row[key] = None
            continue
        # Use only the uninterrupted history leading into this developing candle.
        gaps = bars.index.to_series().diff().gt(step)
        if gaps.any():
            bars = bars.loc[gaps[gaps].index[-1]:]
        if len(bars) and bars.index[-1] != start:
            bars = bars.iloc[:0]
        bar = dict(open=part.open.iloc[0], high=part.high.max(), low=part.low.min(),
                   close=part.close.iloc[-1], volume=part.volume.sum())
        if "taker_buy_volume" in part:
            bar["taker_buy_volume"] = part.taker_buy_volume.sum(min_count=len(part))
        bars.loc[start + step, list(bar)] = list(bar.values())
        values = indicators(bars, tf).iloc[-1]
        for key, value in values.items():
            row[f"{prefix}_{key}"] = value
    return observed, row


def details(minutes, confirmed):
    observed, row = preview(minutes, confirmed)
    breakout, side = agents.trigger(row)
    bias = agents.number(row, "h4_bias")
    side = side or (1 if bias > 0 else -1 if bias < 0 else 0)
    readings = [agents.bias(row, side)[0], agents.structure(row, side), agents.setup(row, side),
                breakout, agents.derivatives(row, side), agents.macro_flows(row), agents.sentiment(row)]
    output = []
    for i, reading in enumerate(readings):
        metrics = {}
        trend = volatility = None
        if i < len(TIERS):
            tf, prefix = TIERS[i]
            fields = {name: f"{prefix}_{name}" for name in METRICS[tf]}
            trend = row.get(f"{prefix}_trend")
            volatility = row.get(f"{prefix}_volatility")
        else:
            fields = ({"funding_rate": "ctx_funding_rate", "oi_change_1h": "ctx_oi_change_1h",
                       "taker_ratio": "ctx_taker_ratio"},
                      {"etf_net_flow_usd": "ctx_etf_net_flow_usd", "event_blackout": "event_blackout"},
                      {"headlines_6h": "news_count", "security_headlines": "news_security_count",
                       "fear_greed": "ctx_fear_greed"})[i - 4]
        for label, key in fields.items():
            value = row.get(key)
            metrics[label] = float(value) if pd.notna(value) else None
        output.append(dict(agent=reading.agent, direction=reading.direction.value, score=reading.score,
                           reason=reading.reasons[0], metrics=metrics,
                           sources={k: str(row[v + "_source"]) for k, v in fields.items()
                                    if pd.notna(row.get(v + "_source"))},
                           trend=trend if pd.notna(trend) else None,
                           volatility=volatility if pd.notna(volatility) else None))
    return {"observed_at": observed.isoformat(), "agent_details": output}
