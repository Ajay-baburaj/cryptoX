"""Deterministic timeframe gates and the master decision."""
from enum import StrEnum
from datetime import datetime
from math import isfinite
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class AgentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent: str
    timestamp: datetime
    source_close: datetime | None = None
    direction: Direction = Direction.NEUTRAL
    score: float = Field(default=0, ge=-1, le=1)
    confidence: float = Field(default=0, ge=0, le=1)
    key_levels: dict[str, list[float]] = Field(default_factory=dict)
    invalidation: float | None = None
    veto: bool = False
    reasons: tuple[str, ...] = ()


class Decision(BaseModel):
    timestamp: str
    action: Literal["LONG", "SHORT", "WATCH", "FLAT"]
    score: float = Field(ge=-1, le=1)
    risk_multiplier: float = Field(ge=0, le=1)
    reason: str
    agents: tuple[AgentResult, ...]
    regime: Literal["TREND", "RANGE", "HIGH_VOL", "unknown"] = "unknown"


# Regime-dependent score weights, carrying the PDF's TREND/RANGE/HIGH_VOL table onto this
# package's agents (key_levels -> structure_1h, volume_orderflow -> trigger_5m,
# momentum -> setup_15m). chart_structure/htf_bias is a veto only (see `bias`), not scored,
# so its PDF weight is folded into the other four and macro_flows/sentiment stay constant.
# Every number here is a default to backtest, not a tuned result.
REGIME_WEIGHTS = {
    "TREND": {"structure_1h": .2429, "setup_15m": .1821, "trigger_5m": .2429,
              "derivatives": .1821, "macro_flows": .10, "sentiment": .05},
    "RANGE": {"structure_1h": .30, "setup_15m": .20, "trigger_5m": .20,
              "derivatives": .15, "macro_flows": .10, "sentiment": .05},
    "HIGH_VOL": {"structure_1h": .2267, "setup_15m": .1133, "trigger_5m": .2833,
                 "derivatives": .2267, "macro_flows": .10, "sentiment": .05},
}
ABLATIONS = ("bias", "structure_1h", "setup_15m", "trigger_5m", "derivatives", "macro_flows", "sentiment")
TIMEFRAME_AGENTS = set(ABLATIONS[:4])


def market_regime(row):
    """TREND/RANGE/HIGH_VOL off the 4h bar, the only higher-timeframe regime signal here."""
    if row.get("h4_volatility") == "high":
        return "HIGH_VOL"
    return "TREND" if number(row, "h4_adx") >= 20 else "RANGE"


def number(row, key):
    value = row.get(key, float("nan"))
    return float(value) if pd.notna(value) else float("nan")


def direction(value):
    return Direction.LONG if value > 0 else Direction.SHORT if value < 0 else Direction.NEUTRAL


def result(agent, timestamp, value=0, reason="", *, veto=False, levels=None, invalidation=None, source_close=None):
    return AgentResult(agent=agent, timestamp=timestamp, direction=direction(value), score=value,
                       confidence=abs(value), reasons=(reason,) if reason else (), veto=veto,
                       key_levels=levels or {}, invalidation=invalidation,
                       source_close=source_close if pd.notna(source_close) else None)


def bias(row, sign):
    bias_value = number(row, "h4_bias")
    agrees = bias_value == sign and number(row, "h4_adx") >= 20
    reason = "4h_range" if number(row, "h4_adx") < 20 else "4h_bias_agrees" if agrees else "4h_bias_unavailable_or_opposed"
    return result("bias", row.name, bias_value if isfinite(bias_value) else 0, reason,
                  veto=not agrees, source_close=row.get("h4_source_close")), 1.0


STRONG_ZONE = 40.0  # 0-100 zone strength floor; default to backtest


def structure(row, sign):
    price, atr = number(row, "m5_close"), number(row, "h1_atr")
    support_low, support_high, support_strength = (
        number(row, key) for key in ("h1_zone_support_low", "h1_zone_support_high", "h1_zone_support_strength"))
    resistance_low, resistance_high, resistance_strength = (
        number(row, key) for key in ("h1_zone_resistance_low", "h1_zone_resistance_high", "h1_zone_resistance_strength"))
    supports = [support_high] if isfinite(support_high) and support_strength >= STRONG_ZONE else []
    resistances = [resistance_low] if isfinite(resistance_low) and resistance_strength >= STRONG_ZONE else []
    locations = supports + resistances
    close_to_level = locations and min(abs(price - level) for level in locations) <= .75 * atr
    aligned = sign * number(row, "h1_momentum") > 0
    agrees = bool(close_to_level and aligned)
    levels = {"support": supports, "resistance": resistances}
    return result("structure_1h", row.name, sign if agrees else 0,
                  "near_1h_level_with_momentum" if agrees else "1h_location_or_momentum_failed",
                  veto=not agrees, levels=levels, source_close=row.get("h1_source_close"))


def setup(row, sign):
    close, ema, atr = (number(row, key) for key in ("m15_close", "m15_ema20", "m15_atr"))
    rsi = number(row, "m15_rsi")
    near_ema = abs(close - ema) <= atr
    momentum = sign * number(row, "m15_macd_hist") > 0
    trend = sign * (close - number(row, "m15_ema50")) > 0 and sign * (rsi - 50) > 0
    agrees = trend and (near_ema or momentum)
    return result("setup_15m", row.name, sign if agrees else 0,
                  "15m_pullback_or_momentum" if agrees else "15m_setup_failed", veto=not agrees,
                  source_close=row.get("m15_source_close"))


def trigger(row):
    close, high, low = (number(row, key) for key in ("m5_close", "m5_range_high", "m5_range_low"))
    sign = 1 if close > high else -1 if close < low else 0
    valid = sign != 0 and number(row, "m5_rvol") >= 1 and number(row, "m5_atr") > 0
    invalidation = high if sign > 0 else low
    agent = result("trigger_5m", row.name, sign if valid else 0,
                   "closed_breakout_with_volume" if valid else "no_breakout_with_volume",
                   veto=not valid, invalidation=invalidation if valid else None, source_close=row.name)
    return agent, sign


def derivatives(row, sign):
    funding, oi = number(row, "ctx_funding_rate"), number(row, "ctx_oi_change_1h")
    crowded = sign * funding >= .0005 and oi >= .03
    imbalance = number(row, "h1_taker_imbalance")
    ratio = number(row, "ctx_taker_ratio")
    if not isfinite(imbalance) and ratio > 0 and isfinite(ratio):
        imbalance = (ratio - 1) / (ratio + 1)
    if crowded:
        return result("derivatives", row.name, -sign, "extreme_funding_and_open_interest_growth", veto=True)
    if isfinite(imbalance):
        return result("derivatives", row.name, max(-1, min(1, 3 * imbalance)), "available_hourly_or_external_taker_flow")
    return result("derivatives", row.name, reason="no_fresh_flow")


def macro_flows(row):
    if row.get("event_blackout", False):
        return result("macro_flows", row.name, reason="scheduled_macro_blackout", veto=True)
    values = []
    etf = number(row, "ctx_etf_net_flow_usd")
    if isfinite(etf):
        values.append(max(-1, min(1, etf / 500_000_000)))
    for return_key, correlation_key in (("dxy_return", "dxy_btc_corr30"), ("nasdaq_return", "nasdaq_btc_corr30")):
        value, corr = number(row, f"ctx_{return_key}"), number(row, f"ctx_{correlation_key}")
        if isfinite(value) and isfinite(corr):
            values.append(max(-1, min(1, 100 * value * corr)))
    return result("macro_flows", row.name, sum(values) / len(values) if values else 0,
                  "published_macro_flow_inputs" if values else "no_fresh_macro_flow_inputs")


def sentiment(row):
    if row.get("news_security_count", 0):
        return result("sentiment", row.name, reason="recent_btc_security_headline")
    fear = number(row, "ctx_fear_greed")
    score = .5 if fear <= 20 else -.5 if fear >= 80 else 0
    reason = "fear_greed_extreme" if score else "headlines_logged_without_direction"
    return result("sentiment", row.name, score, reason)


def decide(row, omit=None, threshold=.6):
    trigger_result, sign = trigger(row)
    timestamp = row.name.isoformat()
    regime = market_regime(row)
    if not sign or (trigger_result.veto and omit != "trigger_5m"):
        return Decision(timestamp=timestamp, action="FLAT", score=0, risk_multiplier=0,
                        reason=trigger_result.reasons[0], agents=(trigger_result,), regime=regime)

    bias_result, size = bias(row, sign)
    structure_result = structure(row, sign)
    setup_result = setup(row, sign)
    agents = (bias_result, structure_result, setup_result, trigger_result,
              derivatives(row, sign), macro_flows(row), sentiment(row))
    active = [agent for agent in agents if agent.agent != omit]
    veto = next((agent for agent in active if agent.veto), None)
    agreement = sum(agent.direction == direction(sign) for agent in active if agent.agent in TIMEFRAME_AGENTS)
    weights = REGIME_WEIGHTS[regime]
    score = sum(weights.get(agent.agent, 0) * agent.score for agent in active)
    if omit in weights:
        score /= 1 - weights[omit]
    score = max(-1, min(1, score))
    action = "FLAT"
    reason = veto.reasons[0] if veto else "score_or_timeframe_agreement"
    if not veto and agreement >= 3:
        if sign * score >= threshold:
            action, reason = direction(sign).value, "qualified"
        elif sign * score >= .4:
            action, reason = "WATCH", "await_confirmation"
    multiplier = (1.0 if omit == "bias" else size)
    if agents[-1].reasons == ("recent_btc_security_headline",) and omit != "sentiment":
        multiplier *= .5
    return Decision(timestamp=timestamp, action=action, score=score, reason=reason,
                    risk_multiplier=multiplier if action in ("LONG", "SHORT") else 0, agents=tuple(active),
                    regime=regime)
