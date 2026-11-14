"""Order-block rejection research toolkit: zones, rejection events, features and 1m exits.

Order blocks come from the LuxAlgo internal-structure port in ``luxalgo_internal_ob``
(CC BY-NC-SA 4.0, non-commercial). Everything here works on closed bars only: a zone is
usable from the close of the higher-timeframe bar that confirmed it, an entry fills at the
next entry-timeframe open, and exits are walked on one-minute candles.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from strategy.luxalgo_internal_ob import OrderBlock, internal_order_blocks, wilder_rma


FEE_PER_SIDE = 0.00059


def clean_minutes(minutes: pd.DataFrame, max_wick: float = 0.03) -> pd.DataFrame:
    """Clip single-print wicks that sit >3% beyond a normal candle body and the local median.

    Real crashes move the body and the median with them, so they are kept; a lone 143k print
    on an 85k market is not tradable and would fake every stop and target it touches.
    """
    out = minutes.copy()
    ref = out["close"].rolling(31, center=True, min_periods=1).median()
    body_hi = out[["open", "close"]].max(axis=1)
    body_lo = out[["open", "close"]].min(axis=1)
    bad_high = (out["high"] > ref * (1 + max_wick)) & (body_hi < ref * (1 + max_wick / 3))
    bad_low = (out["low"] < ref * (1 - max_wick)) & (body_lo > ref * (1 - max_wick / 3))
    out.loc[bad_high, "high"] = body_hi[bad_high]
    out.loc[bad_low, "low"] = body_lo[bad_low]
    return out


def aggregate(minutes: pd.DataFrame, minutes_per_bar: int, coverage: float = 0.9) -> pd.DataFrame:
    """UTC bars labelled by their close time; bins with <90% of their minutes are dropped."""
    bars = minutes.resample(f"{minutes_per_bar}min", closed="left", label="right", origin="start_day").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), minute_count=("close", "count"),
    )
    keep = bars["minute_count"] >= int(minutes_per_bar * coverage)
    return bars.loc[keep].dropna(subset=["open", "high", "low", "close"])


def segment_ids(index: pd.DatetimeIndex, step: pd.Timedelta) -> pd.Series:
    """Number continuous runs of bars; a gap longer than one step starts a new run."""
    return index.to_series().diff().gt(step).cumsum()


def order_blocks(bars: pd.DataFrame, step: pd.Timedelta) -> list[OrderBlock]:
    """LuxAlgo internal OBs, recomputed independently on each continuous data run."""
    blocks: list[OrderBlock] = []
    for _, run in bars.groupby(segment_ids(bars.index, step)):
        found = internal_order_blocks(run)
        offset = len(blocks)
        for block in found:
            block.block_id += offset
        blocks.extend(found)
    return blocks


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = wilder_rma(delta.clip(lower=0).fillna(0), length)
    loss = wilder_rma((-delta).clip(lower=0).fillna(0), length)
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def true_range(bars: pd.DataFrame) -> pd.Series:
    prev = bars["close"].shift(1)
    return pd.concat([bars["high"] - bars["low"], (bars["high"] - prev).abs(), (bars["low"] - prev).abs()], axis=1).max(axis=1)


def adx(bars: pd.DataFrame, length: int = 14) -> pd.Series:
    up = bars["high"].diff()
    down = -bars["low"].diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=bars.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=bars.index)
    atr = wilder_rma(true_range(bars).fillna(0), length)
    plus_di = 100 * wilder_rma(plus, length) / atr
    minus_di = 100 * wilder_rma(minus, length) / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return wilder_rma(dx.fillna(0), length)


def indicators(bars: pd.DataFrame) -> pd.DataFrame:
    """Entry-timeframe indicators, each known at the bar's close."""
    out = pd.DataFrame(index=bars.index)
    out["atr"] = wilder_rma(true_range(bars).fillna(bars["high"] - bars["low"]), 14)
    out["rsi"] = rsi(bars["close"], 14)
    out["adx"] = adx(bars, 14)
    out["ema50"] = ema(bars["close"], 50)
    out["ema200"] = ema(bars["close"], 200)
    out["vol_ratio"] = bars["volume"] / bars["volume"].rolling(50, min_periods=20).mean()
    return out


def htf_trend(minutes: pd.DataFrame, entry_index: pd.DatetimeIndex) -> pd.DataFrame:
    """Higher-timeframe context aligned to entry bars using only already-closed HTF bars."""
    h1 = aggregate(minutes, 60)
    h4 = aggregate(minutes, 240)
    d1 = aggregate(minutes, 1440)
    ctx = pd.DataFrame({
        "h1_ema200_dir": np.sign(h1["close"] - ema(h1["close"], 200)),
        "h1_rsi": rsi(h1["close"], 14),
    })
    ctx4 = pd.DataFrame({
        "h4_ema50_dir": np.sign(h4["close"] - ema(h4["close"], 50)),
        "h4_ema200_dir": np.sign(h4["close"] - ema(h4["close"], 200)),
        "h4_rsi": rsi(h4["close"], 14),
        "h4_adx": adx(h4, 14),
    })
    ctxd = pd.DataFrame({
        "d1_ema20_dir": np.sign(d1["close"] - ema(d1["close"], 20)),
        "d1_ema20_slope": np.sign(ema(d1["close"], 20).diff()),
    })
    frames = []
    for frame in (ctx, ctx4, ctxd):
        frames.append(frame.reindex(entry_index, method="ffill"))
    return pd.concat(frames, axis=1)


@dataclass(frozen=True)
class EventConfig:
    ob_minutes: int = 240
    entry_minutes: int = 15
    rule: str = "wick"  # wick: wick into zone, close outside; inside: opens inside, closes outside


def rejection_events(
    minutes: pd.DataFrame,
    config: EventConfig,
) -> pd.DataFrame:
    """Every closed entry bar that rejects a live order block, with features for filtering.

    A zone is live from its confirming HTF close until an entry bar trades through its far
    side (bullish: low below bottom; bearish: high above top). Each event records which
    rejection of that zone it is (``touch``), so first-touch rules can be tested.
    """
    step_ob = pd.Timedelta(minutes=config.ob_minutes)
    step_entry = pd.Timedelta(minutes=config.entry_minutes)
    htf = aggregate(minutes, config.ob_minutes)
    bars = aggregate(minutes, config.entry_minutes)
    blocks = order_blocks(htf, step_ob)
    ind = indicators(bars)
    ctx = htf_trend(minutes, bars.index)
    times = bars.index
    starts = times - step_entry
    O, H, L, C = (bars[c].to_numpy(dtype=float) for c in ("open", "high", "low", "close"))
    seg = segment_ids(times, step_entry).to_numpy()
    rows: list[dict[str, object]] = []
    for block in blocks:
        first = int(np.searchsorted(starts, block.created_at, side="left"))
        touches = 0
        for t in range(first, len(times)):
            if t > first and seg[t] != seg[t - 1]:
                break  # zones do not survive a data outage
            if block.bias == 1:
                touched = L[t] <= block.top
                if config.rule == "wick":
                    hit = touched and L[t] >= block.bottom and C[t] > block.top
                else:
                    hit = block.bottom <= O[t] <= block.top and C[t] > block.top
                dead = L[t] < block.bottom
            else:
                touched = H[t] >= block.bottom
                if config.rule == "wick":
                    hit = touched and H[t] <= block.top and C[t] < block.bottom
                else:
                    hit = block.bottom <= O[t] <= block.top and C[t] < block.bottom
                dead = H[t] > block.top
            if hit and t + 1 < len(times) and seg[t + 1] == seg[t]:
                touches += 1
                rng = H[t] - L[t]
                body = abs(C[t] - O[t])
                wick = (min(O[t], C[t]) - L[t]) if block.bias == 1 else (H[t] - max(O[t], C[t]))
                rows.append({
                    "signal_time": times[t],
                    "entry_time": times[t + 1] - step_entry,  # next bar's open
                    "entry": O[t + 1],
                    "side": block.bias,
                    "block_id": block.block_id,
                    "touch": touches,
                    "age_h": (times[t] - block.created_at).total_seconds() / 3600,
                    "top": block.top,
                    "bottom": block.bottom,
                    "sig_high": H[t],
                    "sig_low": L[t],
                    "range": rng,
                    "body_frac": body / rng if rng > 0 else 0.0,
                    "wick_frac": wick / rng if rng > 0 else 0.0,
                    "zone_atr": (block.top - block.bottom) / ind["atr"].iat[t],
                    "range_atr": rng / ind["atr"].iat[t],
                    "atr": ind["atr"].iat[t],
                    "rsi": ind["rsi"].iat[t],
                    "adx": ind["adx"].iat[t],
                    "ema50_dir": np.sign(C[t] - ind["ema50"].iat[t]),
                    "ema200_dir": np.sign(C[t] - ind["ema200"].iat[t]),
                    "vol_ratio": ind["vol_ratio"].iat[t],
                    "hour": times[t].hour,
                    **ctx.iloc[t].to_dict(),
                })
            if dead:
                break
    events = pd.DataFrame(rows)
    if events.empty:
        return events
    return events.sort_values(["signal_time", "block_id"]).drop_duplicates("signal_time").reset_index(drop=True)


class MinutePath:
    """One-minute arrays for walking exits; trades end at the last bar before a data gap."""

    def __init__(self, minutes: pd.DataFrame) -> None:
        self.index = minutes.index.as_unit("ns")
        self.ns = self.index.asi8
        self.open = minutes["open"].to_numpy(dtype=float)
        self.high = minutes["high"].to_numpy(dtype=float)
        self.low = minutes["low"].to_numpy(dtype=float)
        self.close = minutes["close"].to_numpy(dtype=float)
        gap = np.diff(self.ns) > pd.Timedelta(minutes=5).value
        # run_end[i] = last minute index of the continuous run containing i
        breaks = np.flatnonzero(gap)
        ends = np.append(breaks, len(self.ns) - 1)
        self.run_end = np.repeat(ends, np.diff(np.concatenate(([-1], ends))))

    def start(self, when: pd.Timestamp) -> int:
        return int(np.searchsorted(self.ns, pd.Timestamp(when).as_unit("ns").value, side="left"))


def walk_exit(
    path: MinutePath,
    start: int,
    side: int,
    entry: float,
    stop: float,
    target: float,
    max_minutes: int,
    breakeven_at: float | None = None,
) -> tuple[int, float, str]:
    """First of stop / target / time-out on 1m bars. Same-minute stop+target counts as stop.

    ``breakeven_at`` (a price) moves the stop to entry once touched; the move applies from the
    following minute, so a minute that tags both the trigger and entry is not given the benefit.
    """
    end = min(start + max_minutes, path.run_end[start] + 1)
    hi, lo = path.high[start:end], path.low[start:end]
    if side == 1:
        sl_hits = lo <= stop
        tp_hits = hi >= target
    else:
        sl_hits = hi >= stop
        tp_hits = lo <= target
    sl_i = int(np.argmax(sl_hits)) if sl_hits.any() else len(hi)
    tp_i = int(np.argmax(tp_hits)) if tp_hits.any() else len(hi)
    if breakeven_at is not None:
        be_hits = (hi >= breakeven_at) if side == 1 else (lo <= breakeven_at)
        be_i = int(np.argmax(be_hits)) if be_hits.any() else len(hi)
        if be_i < min(sl_i, tp_i):
            after = be_i + 1
            be_sl = (lo[after:] <= entry) if side == 1 else (hi[after:] >= entry)
            be_stop_i = after + int(np.argmax(be_sl)) if be_sl.any() else len(hi)
            if be_stop_i < tp_i:
                gap_open = path.open[start + be_stop_i]
                fill = min(entry, gap_open) if side == 1 else max(entry, gap_open)
                return start + be_stop_i, fill, "breakeven"
    if sl_i < len(hi) and sl_i <= tp_i:
        gap_open = path.open[start + sl_i]
        fill = min(stop, gap_open) if side == 1 else max(stop, gap_open)
        return start + sl_i, fill, "stop"
    if tp_i < len(hi):
        gap_open = path.open[start + tp_i]
        fill = max(target, gap_open) if side == 1 else min(target, gap_open)
        return start + tp_i, fill, "target"
    last = end - 1
    return last, path.close[last], "time" if end - start >= max_minutes else "data_gap"


@dataclass(frozen=True)
class ExitConfig:
    stop_mode: str = "zone"  # zone: beyond far side of OB; candle: beyond rejection candle; atr
    stop_buffer_atr: float = 0.25
    target_r: float = 1.0
    max_hours: int = 48
    breakeven_r: float | None = None
    min_stop_pct: float = 0.002  # skip stops so tight that fees dominate


def stop_price(event: pd.Series, exit_config: ExitConfig) -> float:
    side, atr = int(event["side"]), float(event["atr"])
    buffer = exit_config.stop_buffer_atr * atr
    if exit_config.stop_mode == "zone":
        return float(event["bottom"]) - buffer if side == 1 else float(event["top"]) + buffer
    if exit_config.stop_mode == "candle":
        return float(event["sig_low"]) - buffer if side == 1 else float(event["sig_high"]) + buffer
    return float(event["entry"]) - side * (1.0 + exit_config.stop_buffer_atr) * atr


def simulate(
    events: pd.DataFrame,
    path: MinutePath,
    exit_config: ExitConfig,
    fee_per_side: float = FEE_PER_SIDE,
) -> pd.DataFrame:
    """Take events one position at a time (signals during an open trade are skipped)."""
    trades: list[dict[str, object]] = []
    busy_until = -1
    for event in events.itertuples(index=False):
        row = event._asdict()
        start = path.start(row["entry_time"])
        if start >= len(path.ns) or start <= busy_until:
            continue
        side, entry = int(row["side"]), float(path.open[start])
        stop = stop_price(pd.Series(row), exit_config)
        risk = (entry - stop) * side
        if risk <= 0 or risk / entry < exit_config.min_stop_pct:
            continue
        target = entry + side * exit_config.target_r * risk
        be = entry + side * exit_config.breakeven_r * risk if exit_config.breakeven_r else None
        exit_i, fill, reason = walk_exit(path, start, side, entry, stop, target, exit_config.max_hours * 60, be)
        busy_until = exit_i
        gross = side * (fill - entry) / entry
        net = (1 - fee_per_side) * (1 + gross) * (1 - fee_per_side) - 1
        trades.append({
            **{k: row[k] for k in ("signal_time", "ob_tf", "block_id", "touch") if k in row},
            "side": "long" if side == 1 else "short",
            "entry_time": path.index[start],
            "exit_time": path.index[exit_i],
            "entry": entry,
            "stop": stop,
            "target": target,
            "exit": fill,
            "exit_reason": reason,
            "risk_%": risk / entry * 100,
            "ret_gross": gross,
            "ret_net": net,
            "r_net": net / (risk / entry),
        })
    return pd.DataFrame(trades)


def monthly(trades: pd.DataFrame) -> pd.DataFrame:
    """Per-month trade count, win %, summed net return (1x notional) and summed R."""
    if trades.empty:
        return pd.DataFrame(columns=["trades", "win_%", "net_%", "net_R"])
    month = pd.to_datetime(trades["entry_time"], utc=True).dt.strftime("%Y-%m")
    return trades.groupby(month).agg(
        trades=("ret_net", "size"),
        **{"win_%": ("ret_net", lambda s: (s > 0).mean() * 100)},
        **{"net_%": ("ret_net", lambda s: s.sum() * 100)},
        net_R=("r_net", "sum"),
    )


def exit_outcomes(
    events: pd.DataFrame,
    path: MinutePath,
    exit_config: ExitConfig,
    fee_per_side: float = FEE_PER_SIDE,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Per-event (entry minute, exit minute, net return, R) ignoring overlap, for fast grids.

    Events whose stop is invalid or too tight get NaN returns; pair with ``take_sequential``.
    """
    n = len(events)
    starts, ends = np.zeros(n, dtype=int), np.zeros(n, dtype=int)
    rets, r_mult = np.full(n, np.nan), np.full(n, np.nan)
    for k, row in enumerate(events.to_dict("records")):
        start = min(path.start(row["entry_time"]), len(path.ns) - 1)
        starts[k] = ends[k] = start
        side, entry = int(row["side"]), float(path.open[start])
        stop = stop_price(pd.Series(row), exit_config)
        risk = (entry - stop) * side
        if risk <= 0 or risk / entry < exit_config.min_stop_pct:
            continue
        be = entry + side * exit_config.breakeven_r * risk if exit_config.breakeven_r else None
        target = entry + side * exit_config.target_r * risk
        ends[k], fill, _ = walk_exit(path, start, side, entry, stop, target, exit_config.max_hours * 60, be)
        rets[k] = (1 - fee_per_side) ** 2 * (1 + side * (fill - entry) / entry) - 1
        r_mult[k] = rets[k] / (risk / entry)
    return starts, ends, rets, r_mult


def take_sequential(starts: np.ndarray, ends: np.ndarray, rets: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Indices of events actually traded when only one position may be open at a time."""
    busy, taken = -1, []
    for k in np.flatnonzero(mask & ~np.isnan(rets)):
        if starts[k] > busy:
            taken.append(k)
            busy = ends[k]
    return np.array(taken, dtype=int)


@dataclass(frozen=True)
class StrategyConfig:
    """The researched rule set (see scripts/research_ob_rejection.py).

    1h and 4h LuxAlgo internal OBs; a 15m candle wicks into a live zone without breaking its
    far side and closes back outside it; trade only with the 15m EMA200 and only while 4h
    ADX(14) <= 25 (no strong higher-timeframe trend to run the zone over). Stop 0.5 ATR(15m)
    beyond the zone's far side, target 0.5R, 96h time stop, one position at a time.
    """

    ob_minutes: tuple[int, ...] = (60, 240)
    entry_minutes: int = 15
    rule: str = "wick"
    with_ema200: bool = True
    max_h4_adx: float = 25.0
    exit: ExitConfig = ExitConfig(stop_mode="zone", stop_buffer_atr=0.5, target_r=0.5, max_hours=96)


def strategy_events(minutes: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    """Rejection events from every OB timeframe, filtered by the strategy's trend/ADX rules.

    When two timeframes fire on the same entry bar the higher-timeframe zone is kept.
    """
    frames = []
    for ob_minutes in sorted(config.ob_minutes, reverse=True):
        events = rejection_events(minutes, EventConfig(ob_minutes, config.entry_minutes, config.rule))
        if not events.empty:
            frames.append(events.assign(ob_tf=f"{ob_minutes // 60}h" if ob_minutes >= 60 else f"{ob_minutes}m"))
    if not frames:
        return pd.DataFrame()
    events = pd.concat(frames, ignore_index=True).drop_duplicates("signal_time")
    keep = events["h4_adx"] <= config.max_h4_adx
    if config.with_ema200:
        keep &= events["side"] == events["ema200_dir"]
    return events.loc[keep].sort_values("signal_time").reset_index(drop=True)
