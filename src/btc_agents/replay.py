"""One-position, minute-level execution replay and comparison reports."""
from dataclasses import dataclass, replace
from math import isfinite

import numpy as np
import pandas as pd

from .agents import ABLATIONS, decide, number, setup, structure, trigger

MINUTE = pd.Timedelta(minutes=1)
TRADE_COLUMNS = ("decision_at", "entry_at", "exit_at", "side", "entry", "exit", "stop", "target",
                 "notional", "risk_usd", "gross_pnl", "fees", "funding_pnl", "net_pnl", "r",
                 "equity_after", "exit_reason", "regime", "status")


@dataclass(frozen=True)
class ReplayConfig:
    equity: float = 10_000
    risk_fraction: float = .005
    fee_bps: float = 5.9
    friction_bps: float = 4.1  # per side, spread and slippage proxy
    hold_hours: int = 12
    delay_minutes: int = 1

    def __post_init__(self):
        if not (self.equity > 0 and 0 < self.risk_fraction <= 1 and self.hold_hours > 0
                and self.delay_minutes >= 1 and 0 <= self.fee_bps < 10_000
                and 0 <= self.friction_bps < 10_000):
            raise ValueError("Invalid equity, risk, costs, holding period or latency")


@dataclass(frozen=True)
class Candidate:
    time: pd.Timestamp
    side: int
    score: float = 1.0
    size: float = 1.0
    atr: float = 0
    level: float | None = None
    targets: tuple[float, ...] = ()
    regime: str = "unknown"
    fixed_hold: bool = False


def baseline_signal(row):
    signal, side = trigger(row)
    return side if (not signal.veto and side * (number(row, "h4_close") - number(row, "h4_ema50")) > 0
                    and not setup(row, side).veto) else 0


def regime(row):
    if number(row, "h4_adx") < 20:
        return "range"
    bias = number(row, "h4_bias")
    return "bull" if bias > 0 else "bear" if bias < 0 else "unknown"


def candidate_from(row, trigger_result, side):
    levels = structure(row, side).key_levels["resistance" if side == 1 else "support"]
    invalidation = trigger_result.invalidation
    if invalidation is None:
        invalidation = number(row, "m5_range_high" if side == 1 else "m5_range_low")
    shift = row["execution_reference"] - row["m5_close"] if "execution_reference" in row else 0
    return Candidate(row.name, side, atr=number(row, "m5_atr"), level=invalidation + shift,
                     targets=tuple(level + shift for level in levels), regime=regime(row))


def signal_candidates(matrix, *, ablations=False, log=None):
    arms = ("baseline", "full", "breakout", "breakout_4h", "breakout_4h_1h", "breakout_4h_1h_soft",
            "breakout_4h_flow_available", "breakout_4h_flow_aligned")
    if ablations:
        arms += tuple(f"without_{name}" for name in ABLATIONS)
    candidates = {name: [] for name in arms}
    breakouts = matrix.loc[(matrix.m5_close > matrix.m5_range_high)
                           | (matrix.m5_close < matrix.m5_range_low)]
    for stamp, row in breakouts.iterrows():
        trigger_result, side = trigger(row)
        market_regime = regime(row)
        fixed = Candidate(stamp, side, regime=market_regime, fixed_hold=True)
        hourly_flow = number(row, "h1_taker_imbalance")
        h4 = number(row, "h4_momentum")
        hourly = number(row, "h1_momentum")
        # Fixed-hold comparisons share the same availability for the timeframe inputs.
        if isfinite(h4) and isfinite(hourly):
            candidates["breakout"].append(fixed)
        if isfinite(h4) and isfinite(hourly) and side * h4 > 0:
            candidates["breakout_4h"].append(fixed)
            if side * hourly > 0:
                candidates["breakout_4h_1h"].append(fixed)
            candidates["breakout_4h_1h_soft"].append(replace(fixed, size=1.0 if side * hourly > 0 else .5))
            if isfinite(hourly_flow):
                candidates["breakout_4h_flow_available"].append(fixed)
                if side * hourly_flow > 0:
                    candidates["breakout_4h_flow_aligned"].append(fixed)

        base = candidate_from(row, trigger_result, side)
        if baseline_signal(row):
            candidates["baseline"].append(base)
        for name in ("full", *(arm for arm in arms if arm.startswith("without_"))):
            decision = decide(row, omit=name.removeprefix("without_") if name != "full" else None, threshold=.4)
            if decision.risk_multiplier > 0:
                candidates[name].append(replace(base, score=side * decision.score, size=decision.risk_multiplier))
        if log is not None:
            log.write(decide(row).model_dump_json() + "\n")
    return candidates


def risk_plan(candidate, entry, equity, config):
    if not (entry > 0 and equity > 0):
        return None
    if candidate.fixed_hold:
        return np.nan, np.nan, equity * candidate.size, np.nan
    side, atr = candidate.side, candidate.atr
    if not (isfinite(atr) and atr > 0):
        return None
    stop = entry - side * 1.5 * atr
    if candidate.level is not None and isfinite(candidate.level):
        boundary = candidate.level - side * .1 * atr
        stop = min(stop, boundary) if side > 0 else max(stop, boundary)
    risk = side * (entry - stop)
    favorable = [level for level in candidate.targets if side * (level - entry) > 0]
    if stop <= 0 or not favorable:
        return None
    target = min(favorable, key=lambda level: abs(level - entry))
    costs = entry * 2 * (config.fee_bps + config.friction_bps) / 10_000
    if side * (target - entry) - costs < 2 * (risk + costs):
        return None
    risk_budget = equity * config.risk_fraction * candidate.size
    quantity = min(risk_budget / (risk + costs), equity / entry)
    return stop, target, quantity * entry, quantity * (risk + costs)


class Market:
    def __init__(self, minutes, funding=None):
        self.index = minutes.index
        self.ns = self.index.as_unit("ns").asi8
        self.open, self.high, self.low, self.close = (minutes[key].to_numpy() for key in ("open", "high", "low", "close"))
        self.funding = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC")) if funding is None else funding
        self.funding_ns = self.funding.index.as_unit("ns").asi8
        self.funding_cumsum = np.r_[0., self.funding.to_numpy().cumsum()]
        self.gaps = np.r_[np.flatnonzero(np.diff(self.ns) != MINUTE.value) + 1, len(self.ns)]

    def funding_pnl(self, entry, exit_, notional, side):
        a, b = self.funding_ns.searchsorted([entry.value, exit_.value], side="right")
        return -side * notional * (self.funding_cumsum[b] - self.funding_cumsum[a])

    def exit(self, start, due, stop, target, side, cutoff, fixed):
        next_gap = self.gaps[self.gaps.searchsorted(start, side="right")]
        requested = min(due, cutoff - MINUTE)
        last = self.index.searchsorted(requested, side="right") - 1
        end = min(last, next_gap - 1)
        time_fill = self.index[end] == requested
        # The open at the time exit takes precedence over that minute's extremes.
        last_intrabar = end if time_fill else end + 1
        if not fixed:
            lows, highs = self.low[start:last_intrabar], self.high[start:last_intrabar]
            hit_stop = lows <= stop if side > 0 else highs >= stop
            hit_target = highs >= target if side > 0 else lows <= target
            hits = np.flatnonzero(hit_stop | hit_target)
            if hits.size:
                offset = hits[0]
                index = start + offset
                if hit_stop[offset]:
                    return index, min(stop, self.open[index]) if side > 0 else max(stop, self.open[index]), "stop"
                return index, target, "target"
        if time_fill:
            return end, self.open[end], "time" if due <= requested else "window_end"
        return end, self.close[end], "gap_or_missing_exit"


def run(market, candidates, start, end, config, threshold=.6, audit=None):
    equity = config.equity
    rows = []
    occupied_until = start
    for candidate in candidates:
        t = candidate.time
        if t < start:
            continue
        if t >= end:
            break
        reason = "score_below_threshold"
        if candidate.score >= threshold:
            if t < occupied_until:
                reason = "position_open"
            else:
                entry_at = t + config.delay_minutes * MINUTE
                index = market.index.searchsorted(entry_at)
                reason = "missing_entry"
                if index < len(market.index) and market.index[index] == entry_at and entry_at < end - MINUTE:
                    side = candidate.side
                    slip = config.friction_bps / 10_000
                    entry = market.open[index] * (1 + side * slip)
                    plan = risk_plan(candidate, entry, equity, config)
                    reason = "risk_rejected"
                    if plan is not None:
                        stop, target, notional, risk_usd = plan
                        due = entry_at + pd.Timedelta(hours=4 if candidate.fixed_hold else config.hold_hours)
                        exit_i, raw_exit, exit_reason = market.exit(index, due, stop, target, side,
                                                                  end, candidate.fixed_hold)
                        exit_at = market.index[exit_i]
                        occupied_until = exit_at + MINUTE
                        status = "unresolved" if exit_reason == "gap_or_missing_exit" else "closed"
                        exit_ = raw_exit * (1 - side * slip)
                        quantity = notional / entry
                        fees = config.fee_bps / 10_000 * quantity * (entry + exit_)
                        funding = market.funding_pnl(entry_at, exit_at, notional, side)
                        gross = side * quantity * (exit_ - entry)
                        net = gross - fees + funding
                        # Keep a marked value for unresolved trades and disclose them in the scorecard.
                        equity += net
                        rows.append((t, entry_at, exit_at, side, entry, exit_, stop, target, notional, risk_usd,
                                     gross, fees, funding, net, net / risk_usd if risk_usd > 0 else np.nan, equity,
                                     exit_reason, candidate.regime, status))
                        reason = exit_reason
        if audit is not None:
            audit.append((t, reason))
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def scorecard(trades, start, end, equity):
    days = pd.date_range(start.normalize(), (end - pd.Timedelta(nanoseconds=1)).normalize(), freq="D")
    daily = pd.Series(0., index=days)
    closed = trades.loc[trades.status.eq("closed")]
    if not trades.empty:
        totals = trades.groupby(pd.to_datetime(trades.exit_at, utc=True).dt.floor("D")).net_pnl.sum()
        daily.loc[totals.index] = totals
    curve = equity + daily.cumsum()
    prior = curve.shift(fill_value=equity)
    returns = daily / prior
    loss = -closed.net_pnl.clip(upper=0).sum()
    peak = curve.cummax().clip(lower=equity)
    std = returns.std()
    return {
        "trades": len(closed), "unresolved": len(trades) - len(closed),
        "mark_inclusive_net_pct": 100 * daily.sum() / equity,
        "closed_net_pct": 100 * closed.net_pnl.sum() / equity,
        "closed_net_bps_per_trade": (closed.net_pnl / closed.notional).mean() * 10_000,
        "net_bps_per_calendar_day": 10_000 * daily.mean() / equity,
        "funding_pnl": trades.funding_pnl.sum(),
        "win_pct": 100 * closed.net_pnl.gt(0).mean(), "avg_r": closed.r.mean(),
        "closed_trades_per_week": len(closed) * 7 / len(days),
        "closed_profit_factor": closed.net_pnl.clip(lower=0).sum() / loss if loss else np.nan,
        "daily_realized_sharpe": returns.mean() / std * np.sqrt(365) if std > 0 else np.nan,
        "daily_realized_drawdown_pct": 100 * ((peak - curve) / peak).max(),
    }


def forecast_report(market, candidates, start, end, delay_minutes):
    """Evaluate gross directional movement, independently of trade occupancy and exits."""
    rows = []
    for arm, signals in candidates.items():
        selected = [item for item in signals if start <= item.time < end and item.score >= .6]
        if not selected:
            continue
        entries = pd.DatetimeIndex([item.time for item in selected]) + delay_minutes * MINUTE
        sides = np.array([item.side for item in selected])
        entry_rows = market.index.get_indexer(entries)
        for hours in (1, 4, 12):
            exits = entries + pd.Timedelta(hours=hours)
            exit_rows = market.index.get_indexer(exits)
            valid = (entry_rows >= 0) & (exit_rows - entry_rows == hours * 60) & (exits < end)
            realized = 10_000 * sides[valid] * (market.open[exit_rows[valid]] / market.open[entry_rows[valid]] - 1)
            if realized.size:
                rows.append({"arm": arm, "hours": hours, "signals": len(realized), "coverage_pct": 100 * valid.mean(),
                             "mean_gross_bps": float(realized.mean()), "median_gross_bps": float(np.median(realized)),
                             "direction_hit_pct": 100 * float((realized > 0).mean())})
    return pd.DataFrame(rows, columns=["arm", "hours", "signals", "coverage_pct", "mean_gross_bps",
                                       "median_gross_bps", "direction_hit_pct"])


def walk_forward(market, candidates, start, end, config):
    rows = []
    anchor = start
    while anchor + pd.DateOffset(months=8) <= end:
        train_end = anchor + pd.DateOffset(months=6)
        test_end = anchor + pd.DateOffset(months=8)
        thresholds = (.55, .6, .65)
        train = {}
        for threshold in thresholds:
            trades = run(market, candidates["full"], anchor, train_end, config, threshold)
            closed = trades.loc[trades.status.eq("closed")]
            if len(closed) >= 20:
                train[threshold] = trades.net_pnl.sum()
        threshold = max(train, key=lambda t: (train[t], -abs(t - .6))) if train else .6
        for arm, data in candidates.items():
            selected = threshold if arm == "full" or arm.startswith("without_") else .6
            trades = run(market, data, train_end, test_end, config, selected)
            rows.append({"arm": arm, "test_start": train_end, "test_end_exclusive": test_end,
                         "score_threshold": selected, **scorecard(trades, train_end, test_end, config.equity)})
        anchor += pd.DateOffset(months=2)
    return pd.DataFrame(rows)
