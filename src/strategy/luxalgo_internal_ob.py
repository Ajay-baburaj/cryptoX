"""Internal-order-block logic translated from LuxAlgo's SMC Pine indicator.

Based on LuxAlgo, "Smart Money Concepts [LuxAlgo]" Pine v5, licensed
CC BY-NC-SA 4.0: https://creativecommons.org/licenses/by-nc-sa/4.0/.
This adaptation is for non-commercial use and remains CC BY-NC-SA 4.0.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class OrderBlock:
    """A confirmed LuxAlgo-style internal order-block zone."""

    block_id: int
    created_at: pd.Timestamp
    top: float
    bottom: float
    bias: int  # 1 bullish, -1 bearish
    expires_at: pd.Timestamp | None = None


def wilder_rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder's RMA, seeded with the first full simple moving average."""
    values = series.to_numpy(dtype=float)
    output = np.full(len(values), np.nan, dtype=float)
    valid = np.flatnonzero(np.isfinite(values))
    if len(valid) < length:
        return pd.Series(output, index=series.index)
    seed_end = valid[length - 1]
    seed_start = valid[0]
    output[seed_end] = values[valid[:length]].mean()
    for index in range(seed_end + 1, len(values)):
        if np.isfinite(values[index]):
            output[index] = (output[index - 1] * (length - 1) + values[index]) / length
    return pd.Series(output, index=series.index)


def internal_order_blocks(h4: pd.DataFrame, visible_count: int = 5) -> list[OrderBlock]:
    """Recreate default internal BOS/CHoCH blocks and their High/Low mitigation.

    Default LuxAlgo parameters used here: internal structure length 5, ATR(200)
    volatility filter, internal blocks visible (latest five), swing blocks hidden,
    confluence filter off, and mitigation by high/low.
    """
    blocks: list[OrderBlock] = []
    block_id = 0
    atr = wilder_rma(
        pd.concat(
            [
                h4["high"] - h4["low"],
                (h4["high"] - h4["close"].shift(1)).abs(),
                (h4["low"] - h4["close"].shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1),
        200,
    )
    volatile = (h4["high"] - h4["low"]) >= 2 * atr
    parsed_high = h4["high"].where(~volatile, h4["low"]).to_numpy(dtype=float)
    parsed_low = h4["low"].where(~volatile, h4["high"]).to_numpy(dtype=float)
    highs = h4["high"].to_numpy(dtype=float)
    lows = h4["low"].to_numpy(dtype=float)
    closes = h4["close"].to_numpy(dtype=float)
    times = h4.index

    def state() -> dict[str, object]:
        return {"leg": 0, "high": np.nan, "low": np.nan, "high_i": -1, "low_i": -1,
                "crossed_high": False, "crossed_low": False}

    internal = state()
    swing = state()
    active: list[OrderBlock] = []

    def update_pivot(pivot_state: dict[str, object], index: int, size: int) -> tuple[bool, bool]:
        if index < size:
            return False, False
        pivot_index = index - size
        following_highs = highs[pivot_index + 1:index + 1]
        following_lows = lows[pivot_index + 1:index + 1]
        new_high = bool(len(following_highs) and highs[pivot_index] > following_highs.max())
        new_low = bool(len(following_lows) and lows[pivot_index] < following_lows.min())
        next_leg = 0 if new_high else 1 if new_low else int(pivot_state["leg"])
        if next_leg == int(pivot_state["leg"]):
            return False, False
        pivot_state["leg"] = next_leg
        if new_high:
            pivot_state["high"] = highs[pivot_index]
            pivot_state["high_i"] = pivot_index
            if size == 5:
                pivot_state["crossed_high"] = False
            return True, False
        if new_low:
            pivot_state["low"] = lows[pivot_index]
            pivot_state["low_i"] = pivot_index
            if size == 5:
                pivot_state["crossed_low"] = False
            return False, True
        return False, False

    for i, timestamp in enumerate(times):
        prior_internal_high = float(internal["high"])
        prior_internal_low = float(internal["low"])
        previous_close = closes[i - 1] if i else np.nan
        update_pivot(swing, i, 50)
        update_pivot(internal, i, 5)

        bullish_break = (
            i > 0
            and np.isfinite(float(internal["high"]))
            and np.isfinite(prior_internal_high)
            and closes[i] > float(internal["high"])
            and previous_close <= prior_internal_high
            and not bool(internal["crossed_high"])
            and np.isfinite(float(swing["high"]))
            and float(internal["high"]) != float(swing["high"])
        )
        bearish_break = (
            i > 0
            and np.isfinite(float(internal["low"]))
            and np.isfinite(prior_internal_low)
            and closes[i] < float(internal["low"])
            and previous_close >= prior_internal_low
            and not bool(internal["crossed_low"])
            and np.isfinite(float(swing["low"]))
            and float(internal["low"]) != float(swing["low"])
        )

        if bullish_break:
            internal["crossed_high"] = True
            pivot_i = int(internal["high_i"])
            if 0 <= pivot_i < i:
                selected = pivot_i + int(np.argmin(parsed_low[pivot_i:i]))
                top, bottom = parsed_high[selected], parsed_low[selected]
                if top > bottom:
                    block_id += 1
                    block = OrderBlock(block_id, timestamp, float(top), float(bottom), 1)
                    blocks.append(block)
                    active.insert(0, block)
                    if len(active) > 100:
                        removed = active.pop()
                        removed.expires_at = timestamp
        if bearish_break:
            internal["crossed_low"] = True
            pivot_i = int(internal["low_i"])
            if 0 <= pivot_i < i:
                selected = pivot_i + int(np.argmax(parsed_high[pivot_i:i]))
                top, bottom = parsed_high[selected], parsed_low[selected]
                if top > bottom:
                    block_id += 1
                    block = OrderBlock(block_id, timestamp, float(top), float(bottom), -1)
                    blocks.append(block)
                    active.insert(0, block)
                    if len(active) > 100:
                        removed = active.pop()
                        removed.expires_at = timestamp

        remaining: list[OrderBlock] = []
        for block in active:
            mitigated = (block.bias == -1 and highs[i] > block.top) or (
                block.bias == 1 and lows[i] < block.bottom
            )
            if mitigated:
                block.expires_at = timestamp
            else:
                remaining.append(block)
        active = remaining

    if len(times):
        end = times[-1] + pd.Timedelta(hours=4)
        for block in active:
            if block.expires_at is None:
                block.expires_at = end
    return blocks


def pine_internal_blocks(bars: pd.DataFrame, show_last: int = 5) -> tuple[list[OrderBlock], list[tuple[int, ...]]]:
    """Internal order blocks exactly as the user's Pine script (order_block_new.txt) builds and draws them.

    Differences from ``internal_order_blocks`` (the newer LuxAlgo port): volatile candles
    (range >= 2 x ATR(200) at that bar) are skipped rather than high/low-swapped; the block is
    the extreme candle strictly between the pivot and the break bar; a block is removed on a
    CLOSE through it (not a wick), and each bar only the newest block of each type is tested
    (the script's ``array.indexof(type, element)`` quirk), so older broken zones can linger;
    only the newest ``show_last`` blocks of either type are drawn.

    Returns every block (``expires_at`` = bar close that removed it) and, per bar, the ids of the
    drawn blocks as of that bar's close.
    """
    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    times = bars.index
    prev_close = bars["close"].shift(1)
    tr = pd.concat([bars["high"] - bars["low"], (bars["high"] - prev_close).abs(), (bars["low"] - prev_close).abs()], axis=1).max(axis=1)
    atr = wilder_rma(tr, 200).to_numpy(dtype=float)
    calm = (highs - lows) < atr * 2  # NaN ATR -> False, as in Pine

    def state() -> dict[str, object]:
        return {"leg": 0, "high": np.nan, "low": np.nan, "high_i": -1, "low_i": -1,
                "crossed_high": False, "crossed_low": False}

    internal, swing = state(), state()

    def update_pivot(s: dict[str, object], index: int, size: int) -> None:
        if index < size:
            return
        p = index - size
        new_high = highs[p] > highs[p + 1:index + 1].max()
        new_low = lows[p] < lows[p + 1:index + 1].min()
        nxt = 0 if new_high else 1 if new_low else int(s["leg"])
        if nxt == int(s["leg"]):
            return
        s["leg"] = nxt
        if new_high:
            s["high"], s["high_i"] = highs[p], p
            if size == 5:
                s["crossed_high"] = False
        else:
            s["low"], s["low_i"] = lows[p], p
            if size == 5:
                s["crossed_low"] = False

    blocks: list[OrderBlock] = []
    arr: list[OrderBlock] = []  # newest first, as array.unshift
    visible: list[tuple[int, ...]] = []
    for i, ts in enumerate(times):
        prior_high, prior_low = float(internal["high"]), float(internal["low"])
        update_pivot(swing, i, 50)
        update_pivot(internal, i, 5)
        prev = closes[i - 1] if i else np.nan
        bull = (i > 0 and np.isfinite(float(internal["high"])) and np.isfinite(prior_high)
                and closes[i] > float(internal["high"]) and prev <= prior_high and not internal["crossed_high"]
                and np.isfinite(float(swing["high"])) and float(internal["high"]) != float(swing["high"]))
        bear = (i > 0 and np.isfinite(float(internal["low"])) and np.isfinite(prior_low)
                and closes[i] < float(internal["low"]) and prev >= prior_low and not internal["crossed_low"]
                and np.isfinite(float(swing["low"])) and float(internal["low"]) != float(swing["low"]))
        for is_bull, fired in ((True, bull), (False, bear)):
            if not fired:
                continue
            if is_bull:
                internal["crossed_high"] = True
                loc = int(internal["high_i"])
            else:
                internal["crossed_low"] = True
                loc = int(internal["low_i"])
            window = np.arange(loc + 1, i)
            window = window[calm[window]] if len(window) else window
            if len(window) == 0:
                continue  # Pine would add a garbage block and delete it again in the same bar
            pick = window[np.argmin(lows[window])] if is_bull else window[np.argmax(highs[window])]
            block = OrderBlock(len(blocks) + 1, ts, float(highs[pick]), float(lows[pick]), 1 if is_bull else -1)
            blocks.append(block)
            arr.insert(0, block)
        for bias in [b.bias for b in arr]:  # snapshot of types, each tested against the newest block of that type
            newest = next((b for b in arr if b.bias == bias), None)
            if newest is None:
                continue
            if (bias == 1 and closes[i] < newest.bottom) or (bias == -1 and closes[i] > newest.top):
                newest.expires_at = ts
                arr.remove(newest)
        visible.append(tuple(b.block_id for b in arr[:show_last]))
    return blocks, visible
