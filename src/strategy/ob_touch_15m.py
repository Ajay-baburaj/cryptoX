"""Pure 15m order-block touch/near-touch strategy with an ATR trailing stop.

Order blocks come from the same LuxAlgo internal-structure port used by ``ob_rejection``
(CC BY-NC-SA 4.0, non-commercial), computed directly on 15m candles instead of 1h/4h. Unlike
``ob_rejection`` (which waits for a 15m candle to wick into a higher-timeframe zone and close
back outside it), this strategy enters the moment price trades into the zone or within a
configurable buffer of its near edge ("near or touch"): some reversals never actually reach
the zone before turning. The initial stop sits beyond the block's far side; once the trade is
ahead by ``trail_activate_r``, the stop ratchets behind price by ``trail_atr_mult`` x ATR
instead of taking a fixed target, so a strong move keeps running. Entry and exit are both
walked on one-minute candles (via the same ``MinutePath`` used by ``ob_rejection``) so a
15m-bar touch is resolved to the exact minute and fill price, matching how the live paper
engine would actually fill an order.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from strategy.luxalgo_internal_ob import OrderBlock, pine_internal_blocks, wilder_rma
from strategy.ob_rejection import FEE_PER_SIDE, MinutePath, aggregate, order_blocks, true_range


@dataclass(frozen=True)
class EntryConfig:
    entry_minutes: int = 15
    near_mode: str = "pct"  # "touch" (buffer=0) | "atr" | "pct"
    near_atr_mult: float = 0.25
    near_pct: float = 0.0025
    first_touch_only: bool = True
    ob_source: str = "pine"  # "pine" = the user's script exactly (close mitigation, latest N drawn) | "port"
    visible_last: int = 5  # pine only: how many newest blocks are drawn (and tradable); 0 = all live


@dataclass(frozen=True)
class TrailConfig:
    stop_buffer_atr: float = 0.25
    trail_activate_r: float = 1.0
    trail_atr_mult: float = 1.0
    max_hours: int = 96
    min_stop_pct: float = 0.002


@dataclass(frozen=True)
class StrategyConfig:
    """Entering within 0.25% of a 15m order block's near edge, trailing 1x ATR once 1R ahead.

    Research found no edge (48% wins, 0 of 63 grid settings robust, null test ~50%); see the
    STATUS note in config/ob_touch_15m.yaml. Kept as a documented negative result.
    """

    entry: EntryConfig = EntryConfig()
    trail: TrailConfig = TrailConfig()

    @classmethod
    def load(cls, path: str | Path) -> "StrategyConfig":
        """Load ``entry:`` and ``trail:`` blocks from a YAML file (see config/ob_touch_15m.yaml)."""
        raw = yaml.safe_load(Path(path).read_text())
        strategy = dict(raw["strategy"])
        strategy.pop("symbol", None)

        def build(dataclass_type, values: dict) -> object:
            known = {f.name for f in fields(dataclass_type)}
            unknown = set(values) - known
            if unknown:
                raise ValueError(f"Unknown {dataclass_type.__name__} keys: {sorted(unknown)}")
            return dataclass_type(**values)

        entry = build(EntryConfig, strategy.get("entry", {}))
        trail = build(TrailConfig, strategy.get("trail", {}))
        return cls(entry=entry, trail=trail)


def blocks_15m(minutes: pd.DataFrame, entry_minutes: int = 15) -> tuple[pd.DataFrame, list[OrderBlock]]:
    """15m bars and the LuxAlgo internal order blocks confirmed on them."""
    bars = aggregate(minutes, entry_minutes)
    blocks = order_blocks(bars, pd.Timedelta(minutes=entry_minutes))
    return bars, blocks


def pine_touch_candidates(bars: pd.DataFrame, blocks: list[OrderBlock], visible: list[tuple[int, ...]],
                          config: EntryConfig) -> pd.DataFrame:
    """Touch/near-touch of a block that was drawn as of the previous bar's close.

    ``visible[k]`` is the set of drawn blocks after bar ``k`` closed, so bar ``k+1`` (whose minutes
    start at that close) is the first bar that can trade them. ATR is taken from bar ``k`` too.
    """
    atr = wilder_rma(true_range(bars).fillna(bars["high"] - bars["low"]), 14).to_numpy(dtype=float)
    times = bars.index
    H, L = bars["high"].to_numpy(dtype=float), bars["low"].to_numpy(dtype=float)
    by_id = {b.block_id: b for b in blocks}
    step = pd.Timedelta(minutes=config.entry_minutes)
    done: set[int] = set()
    rows: list[dict[str, object]] = []
    for k in range(1, len(bars)):
        if times[k] - times[k - 1] != step:
            continue
        a = float(atr[k - 1]) if np.isfinite(atr[k - 1]) else 0.0
        for block_id in visible[k - 1]:
            if config.first_touch_only and block_id in done:
                continue
            block = by_id[block_id]
            if config.near_mode == "touch":
                buffer = 0.0
            elif config.near_mode == "atr":
                buffer = config.near_atr_mult * a
            elif config.near_mode == "pct":
                buffer = config.near_pct * (block.top if block.bias == 1 else block.bottom)
            else:
                raise ValueError(f"Unknown near_mode: {config.near_mode}")
            trigger = block.top + buffer if block.bias == 1 else block.bottom - buffer
            if not ((L[k] <= trigger) if block.bias == 1 else (H[k] >= trigger)):
                continue
            done.add(block_id)
            edge = block.top if block.bias == 1 else block.bottom
            rows.append({
                "signal_time": times[k], "bar_start": times[k] - step, "side": block.bias, "block_id": block_id,
                "block_created_at": block.created_at, "top": block.top, "bottom": block.bottom,
                "trigger_level": trigger, "touch_type": "touch" if buffer == 0 else "near", "near_buffer": buffer,
                "distance_pct": abs(edge - trigger) / edge * 100, "atr": a, "candle_low": L[k], "candle_high": H[k],
            })
    return pd.DataFrame(rows)


def near_touch_candidates(bars: pd.DataFrame, blocks: list[OrderBlock], config: EntryConfig) -> pd.DataFrame:
    """First 15m bar (per live block) whose range touches or nears the block's near edge.

    "Touch" means price trades into the zone (bullish: low <= top; bearish: high >= bottom).
    "Near" widens that trigger outward by a buffer, so a reversal that stalls just short of the
    zone is still caught. Each block contributes at most one candidate (its first touch/near).
    """
    atr = wilder_rma(true_range(bars).fillna(bars["high"] - bars["low"]), 14)
    times = bars.index
    O, H, L, C = (bars[c].to_numpy(dtype=float) for c in ("open", "high", "low", "close"))
    rows: list[dict[str, object]] = []
    for block in blocks:
        # bars are labelled by close time and created_at is the confirming bar's close, so the
        # first usable bar is the next one (its open >= created_at); "left" would let the
        # confirming bar itself fill an order before the block existed
        start_i = int(times.searchsorted(block.created_at, side="right"))
        if start_i >= len(times):
            continue
        end_time = block.expires_at if block.expires_at is not None else times[-1] + pd.Timedelta(minutes=1)
        end_i = int(times.searchsorted(end_time, side="right"))
        if end_i <= start_i:
            continue
        a = float(atr.iloc[start_i])
        if not np.isfinite(a):
            valid_atr = atr.iloc[:start_i + 1].dropna()
            a = float(valid_atr.iloc[-1]) if len(valid_atr) else 0.0
        if config.near_mode == "touch":
            buffer = 0.0
        elif config.near_mode == "atr":
            buffer = config.near_atr_mult * a
        elif config.near_mode == "pct":
            anchor = block.top if block.bias == 1 else block.bottom
            buffer = config.near_pct * anchor
        else:
            raise ValueError(f"Unknown near_mode: {config.near_mode}")
        if block.bias == 1:
            trigger_level = block.top + buffer
            hit = L[start_i:end_i] <= trigger_level
        else:
            trigger_level = block.bottom - buffer
            hit = H[start_i:end_i] >= trigger_level
        if not hit.any():
            continue
        k = start_i + int(np.argmax(hit))
        zone_edge = block.top if block.bias == 1 else block.bottom
        distance_pct = abs(zone_edge - trigger_level) / zone_edge * 100
        rows.append({
            "signal_time": times[k],
            "bar_start": times[k] - pd.Timedelta(minutes=config.entry_minutes),
            "side": block.bias,
            "block_id": block.block_id,
            "block_created_at": block.created_at,
            "top": block.top,
            "bottom": block.bottom,
            "trigger_level": trigger_level,
            "touch_type": "touch" if buffer == 0 else "near",
            "near_buffer": buffer,
            "distance_pct": distance_pct,
            "atr": a,
            "candle_low": L[k],
            "candle_high": H[k],
        })
    events = pd.DataFrame(rows)
    if events.empty:
        return events
    return events.sort_values(["signal_time", "block_id"]).reset_index(drop=True)


def locate_fill(path: MinutePath, bar_start: pd.Timestamp, bar_minutes: int, side: int,
                 trigger_level: float) -> tuple[int, float] | None:
    """The exact minute within a 15m bar that first crosses the trigger level, and its fill."""
    start = path.start(bar_start)
    if start >= len(path.ns):
        return None
    end = min(start + bar_minutes, path.run_end[start] + 1)
    hi, lo = path.high[start:end], path.low[start:end]
    hits = (lo <= trigger_level) if side == 1 else (hi >= trigger_level)
    if not hits.any():
        return None
    i = start + int(np.argmax(hits))
    gap_open = path.open[i]
    fill = min(trigger_level, gap_open) if side == 1 else max(trigger_level, gap_open)
    return i, fill


def build_entries(candidates: pd.DataFrame, path: MinutePath, entry_minutes: int) -> pd.DataFrame:
    """Resolve each 15m-bar candidate to its exact minute and live fill price."""
    if candidates.empty:
        return candidates
    rows: list[dict[str, object]] = []
    for row in candidates.to_dict("records"):
        located = locate_fill(path, row["bar_start"], entry_minutes, int(row["side"]), row["trigger_level"])
        if located is None:
            continue
        i, fill = located
        rows.append({**row, "entry_i": i, "entry_time": path.index[i], "entry": fill})
    entries = pd.DataFrame(rows)
    if entries.empty:
        return entries
    return entries.sort_values("entry_time").reset_index(drop=True)


def walk_trailing_exit(
    path: MinutePath,
    start: int,
    side: int,
    entry: float,
    stop0: float,
    atr: float,
    trail: TrailConfig,
) -> tuple[int, float, str, float]:
    """Walk 1m bars: hard stop until ``trail_activate_r`` R ahead, then an ATR trailing stop.

    The stop level active during minute ``i`` is the one set by minute ``i - 1``'s extreme (or
    the initial stop for the entry minute), so the ratchet never uses a minute's own extreme to
    dodge its own stop. Returns (exit index, fill price, reason, final stop level).
    """
    max_minutes = trail.max_hours * 60
    end = min(start + max_minutes, path.run_end[start] + 1)
    risk = abs(entry - stop0)
    activate_dist = trail.trail_activate_r * risk
    stop = stop0
    trailing = False
    for i in range(start, end):
        hi, lo = path.high[i], path.low[i]
        hit = (lo <= stop) if side == 1 else (hi >= stop)
        if hit:
            gap_open = path.open[i]
            fill = min(stop, gap_open) if side == 1 else max(stop, gap_open)
            reason = "trail_stop" if trailing else "stop"
            return i, fill, reason, stop
        favorable = hi if side == 1 else lo
        if not trailing and (favorable - entry) * side >= activate_dist:
            trailing = True
        if trailing:
            candidate = favorable - side * trail.trail_atr_mult * atr
            stop = max(stop, candidate) if side == 1 else min(stop, candidate)
    last = end - 1
    reason = "time" if end - start >= max_minutes else "data_gap"
    return last, path.close[last], reason, stop


def simulate(entries: pd.DataFrame, path: MinutePath, trail: TrailConfig,
             fee_per_side: float = FEE_PER_SIDE) -> pd.DataFrame:
    """Take entries one position at a time (signals during an open trade are skipped)."""
    if entries.empty:
        return entries
    trades: list[dict[str, object]] = []
    busy_until = -1
    for row in entries.to_dict("records"):
        if row["entry_i"] <= busy_until:
            continue
        side, entry, atr = int(row["side"]), float(row["entry"]), float(row["atr"])
        stop0 = (row["bottom"] - trail.stop_buffer_atr * atr) if side == 1 else (row["top"] + trail.stop_buffer_atr * atr)
        risk = (entry - stop0) * side
        if risk <= 0 or risk / entry < trail.min_stop_pct:
            continue
        exit_i, fill, reason, final_stop = walk_trailing_exit(path, int(row["entry_i"]), side, entry, stop0, atr, trail)
        busy_until = exit_i
        gross = side * (fill - entry) / entry
        net = (1 - fee_per_side) * (1 + gross) * (1 - fee_per_side) - 1
        trades.append({
            "signal_time": row["signal_time"],
            "block_id": row["block_id"],
            "touch_type": row["touch_type"],
            "distance_pct": row["distance_pct"],
            "side": "long" if side == 1 else "short",
            "top": row["top"],
            "bottom": row["bottom"],
            "entry_time": path.index[int(row["entry_i"])],
            "exit_time": path.index[exit_i],
            "entry": entry,
            "stop0": stop0,
            "final_stop": final_stop,
            "exit": fill,
            "exit_reason": reason,
            "risk_%": risk / entry * 100,
            "ret_net": net,
            "r_net": net / (risk / entry),
        })
    return pd.DataFrame(trades)


def strategy_events(minutes: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    """15m order blocks, their touch/near candidates, and the exact-minute entries."""
    if config.entry.ob_source == "pine":
        bars = aggregate(minutes, config.entry.entry_minutes)
        blocks, visible = pine_internal_blocks(bars, config.entry.visible_last or 10**6)
        candidates = pine_touch_candidates(bars, blocks, visible, config.entry)
    else:
        bars, blocks = blocks_15m(minutes, config.entry.entry_minutes)
        candidates = near_touch_candidates(bars, blocks, config.entry)
    if config.entry.first_touch_only and not candidates.empty:
        candidates = candidates.sort_values("signal_time").drop_duplicates("block_id", keep="first")
    path = MinutePath(minutes)
    entries = build_entries(candidates, path, config.entry.entry_minutes)
    return entries


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


def directional_edge(entries: pd.DataFrame, path: MinutePath,
                      horizons_hours: tuple[int, ...] = (1, 4, 24)) -> pd.DataFrame:
    """Forward-return hit rate at fixed horizons from the entry fill, ignoring stop/trail.

    Tests whether the near/touch signal predicts direction at all, independent of the stop and
    trailing-stop placement scheme used by ``simulate``.
    """
    if entries.empty:
        return pd.DataFrame(columns=["horizon_h", "n", "hit_rate_%", "avg_ret_%"])
    rows = []
    for hours in horizons_hours:
        rets = []
        for row in entries.to_dict("records"):
            i, side, entry = int(row["entry_i"]), int(row["side"]), float(row["entry"])
            j = min(i + hours * 60, path.run_end[i])
            rets.append(side * (path.close[j] - entry) / entry)
        rets_arr = np.array(rets)
        rows.append({
            "horizon_h": hours,
            "n": len(rets_arr),
            "hit_rate_%": float((rets_arr > 0).mean() * 100),
            "avg_ret_%": float(rets_arr.mean() * 100),
        })
    return pd.DataFrame(rows)
