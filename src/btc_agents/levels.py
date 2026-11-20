"""Causal support/resistance zones from confirmed swing pivots on one timeframe's own bars.

Every value a bar reports here is computed from pivots already confirmed by that bar's
close. A pivot needs `right` closed bars after it to confirm, so nothing here ever looks
ahead of the bar it is attached to; see tests/test_levels.py for the truncation proof.
All thresholds (pivot look-back/right, merge tolerance, strength weights, decay) are
defaults to backtest, matching the rest of this package's point-in-time style.
"""
import numpy as np
import pandas as pd

# left/right bars required either side of a candidate pivot before it confirms.
PIVOT_LR = {"4h": 5, "1h": 3, "15m": 3}
# relative weight of a timeframe's own structure in the combined strength score.
TF_WEIGHT = {"4h": 3.0, "1h": 2.0, "15m": 1.0}
MAX_STRENGTH_RAW = max(TF_WEIGHT.values()) + 4 + 1  # weight + capped touches + full recency


def _pivots(high, low, left, right):
    """Boolean masks, aligned to `high`/`low`, marking confirmed strict swing pivots."""
    n = len(high)
    is_high, is_low = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    h, l = high.to_numpy(), low.to_numpy()
    for i in range(left, n - right):
        window_h = h[i - left:i + right + 1]
        window_l = l[i - left:i + right + 1]
        if h[i] == window_h.max() and (window_h == h[i]).sum() == 1:
            is_high[i] = True
        if l[i] == window_l.min() and (window_l == l[i]).sum() == 1:
            is_low[i] = True
    return is_high, is_low


def zone_levels(bars, tf, merge_atr_mult=0.35, decay_bars=100, max_zones=200):
    """Nearest scored support/resistance zone below and above price, bar by bar.

    `bars` needs `high`, `low`, `close` and an already-computed `atr` column (Wilder
    ATR(14) from features.indicators). Returns a frame aligned to `bars.index` with
    zone_{support,resistance}_{low,high,strength}; strength is 0-100.
    """
    left = right = PIVOT_LR.get(tf, 3)
    high, low, close, atr = bars.high, bars.low, bars.close, bars.atr
    n = len(bars)
    out = {key: np.full(n, np.nan) for key in
           ("zone_support_low", "zone_support_high", "zone_resistance_low", "zone_resistance_high")}
    out["zone_support_strength"] = np.zeros(n)
    out["zone_resistance_strength"] = np.zeros(n)
    if n <= left + right:
        return pd.DataFrame(out, index=bars.index)

    is_high, is_low = _pivots(high, low, left, right)
    weight = TF_WEIGHT.get(tf, 1.0)
    atr_values = atr.to_numpy()
    close_values = close.to_numpy()
    high_values = high.to_numpy()
    low_values = low.to_numpy()
    zones = []  # each: {"low": float, "high": float, "touches": int, "last_idx": int}

    def merge_or_add(price, idx, tolerance):
        for zone in zones:
            if zone["low"] - tolerance <= price <= zone["high"] + tolerance:
                zone["low"] = min(zone["low"], price)
                zone["high"] = max(zone["high"], price)
                zone["touches"] += 1
                zone["last_idx"] = idx
                return
        zones.append({"low": price, "high": price, "touches": 1, "last_idx": idx})
        if len(zones) > max_zones:
            zones.sort(key=lambda z: z["last_idx"])
            del zones[0]

    for i in range(n):
        confirm_at = i - right
        if confirm_at >= left and (is_high[confirm_at] or is_low[confirm_at]):
            price = high_values[confirm_at] if is_high[confirm_at] else low_values[confirm_at]
            tolerance = merge_atr_mult * atr_values[confirm_at]
            if np.isfinite(tolerance) and tolerance > 0:
                merge_or_add(float(price), confirm_at, tolerance)
        if not zones:
            continue
        price = close_values[i]
        best_support = best_resistance = None
        for zone in zones:
            mid = (zone["low"] + zone["high"]) / 2
            age = i - zone["last_idx"]
            raw_strength = weight + min(zone["touches"], 4) + np.exp(-age / decay_bars)
            strength = min(100.0, 100.0 * raw_strength / MAX_STRENGTH_RAW)
            if mid <= price:
                distance = price - zone["high"]
                if best_support is None or distance < best_support[0]:
                    best_support = (distance, zone, strength)
            else:
                distance = zone["low"] - price
                if best_resistance is None or distance < best_resistance[0]:
                    best_resistance = (distance, zone, strength)
        if best_support is not None:
            _, zone, strength = best_support
            out["zone_support_low"][i], out["zone_support_high"][i] = zone["low"], zone["high"]
            out["zone_support_strength"][i] = strength
        if best_resistance is not None:
            _, zone, strength = best_resistance
            out["zone_resistance_low"][i], out["zone_resistance_high"][i] = zone["low"], zone["high"]
            out["zone_resistance_strength"][i] = strength

    return pd.DataFrame(out, index=bars.index)
