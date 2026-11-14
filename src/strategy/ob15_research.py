"""Research helpers for diagnosing the 15m order-block touch strategy (see scripts/research_ob15_diagnosis.py).

Nothing here is a live strategy: a flexible exit walker (hard stop, optional target, optional
break-even, optional ATR trail, optional time exit) that reproduces ``walk_trailing_exit`` when
only the trail is enabled, a first-passage barrier table for entry quality, and trade metrics.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from strategy.ob_rejection import FEE_PER_SIDE, MinutePath

FEE_ROUND_TRIP = 2 * FEE_PER_SIDE


@dataclass(frozen=True)
class ExitSpec:
    activate_r: float | None = 1.0   # trail starts once this many R ahead (None = never trail)
    trail_atr_mult: float = 1.0
    be_r: float | None = None        # stop moves to entry once this many R ahead
    target_r: float | None = None    # fixed target in R (None = none)
    max_minutes: int = 96 * 60
    label: str = ""


def walk_exit_variant(path: MinutePath, start: int, side: int, entry: float, stop0: float, atr: float,
                      spec: ExitSpec) -> tuple[int, float, str, float, float]:
    """Walk 1m bars. Returns (exit index, fill, reason, mfe_r, final_stop).

    Same-minute ordering is conservative: the stop active entering a minute is tested first, then
    the target, and only then do the minute's extremes move the stop (a minute never rescues itself).
    """
    risk = abs(entry - stop0)
    end = min(start + spec.max_minutes, path.run_end[start] + 1)
    stop, trailing, be_done, mfe = stop0, False, False, 0.0
    target = entry + side * spec.target_r * risk if spec.target_r is not None else None
    for i in range(start, end):
        hi, lo, op = path.high[i], path.low[i], path.open[i]
        if (lo <= stop) if side == 1 else (hi >= stop):
            fill = min(stop, op) if side == 1 else max(stop, op)
            return i, fill, ("trail_stop" if (trailing or be_done) else "stop"), mfe, stop
        if target is not None and ((hi >= target) if side == 1 else (lo <= target)):
            fill = max(target, op) if side == 1 else min(target, op)
            return i, fill, "target", mfe, stop
        fav = hi if side == 1 else lo
        mfe = max(mfe, (fav - entry) * side / risk)
        if spec.be_r is not None and not be_done and (fav - entry) * side >= spec.be_r * risk:
            be_done = True
            stop = max(stop, entry) if side == 1 else min(stop, entry)
        if spec.activate_r is not None and not trailing and (fav - entry) * side >= spec.activate_r * risk:
            trailing = True
        if trailing:
            cand = fav - side * spec.trail_atr_mult * atr
            stop = max(stop, cand) if side == 1 else min(stop, cand)
    last = end - 1
    return last, path.close[last], ("time" if end - start >= spec.max_minutes else "data_gap"), mfe, stop


def net_return(side: int, entry: float, fill: float, fee_per_side: float = FEE_PER_SIDE) -> tuple[float, float]:
    gross = side * (fill - entry) / entry
    return gross, (1 - fee_per_side) * (1 + gross) * (1 - fee_per_side) - 1


def eval_independent(rows: pd.DataFrame, path: MinutePath, spec: ExitSpec, stop_mode: str = "far",
                     stop_param: float = 0.25, min_stop_pct: float = 0.002) -> pd.DataFrame:
    """Run every entry on its own (no one-position-at-a-time), so exit rules are compared on equal trades."""
    out: list[dict[str, object]] = []
    for r in rows.to_dict("records"):
        side, entry, atr = int(r["side"]), float(r["entry"]), float(r["atr"])
        if stop_mode == "far":
            stop0 = (r["bottom"] - stop_param * atr) if side == 1 else (r["top"] + stop_param * atr)
        elif stop_mode == "near":
            stop0 = (r["top"] - stop_param * atr) if side == 1 else (r["bottom"] + stop_param * atr)
        elif stop_mode == "mid":
            stop0 = (r["top"] + r["bottom"]) / 2
        elif stop_mode == "atr":
            stop0 = entry - side * stop_param * atr
        elif stop_mode == "pct":
            stop0 = entry * (1 - side * stop_param)
        elif stop_mode == "col":
            stop0 = float(r["stop0"])
        else:
            raise ValueError(stop_mode)
        risk = (entry - stop0) * side
        if risk <= 0 or risk / entry < min_stop_pct:
            continue
        exit_i, fill, reason, mfe, final_stop = walk_exit_variant(path, int(r["entry_i"]), side, entry, stop0, atr, spec)
        gross, net = net_return(side, entry, fill)
        risk_frac = risk / entry
        out.append({
            "idx": r.get("idx"), "entry_time": path.index[int(r["entry_i"])], "side": side,
            "risk_%": risk_frac * 100, "exit_reason": reason, "minutes": exit_i - int(r["entry_i"]),
            "mfe_r": mfe, "ret_gross": gross, "ret_net": net, "r_gross": gross / risk_frac, "r_net": net / risk_frac,
        })
    return pd.DataFrame(out)


def summarize(trades: pd.DataFrame) -> dict[str, float]:
    if trades.empty:
        return {"n": 0, "win_%": np.nan, "mean_R": np.nan, "gross_R": np.nan, "sum_net_%": 0.0, "PF": np.nan}
    wins = trades.loc[trades["ret_net"] > 0, "ret_net"].sum()
    losses = abs(trades.loc[trades["ret_net"] <= 0, "ret_net"].sum())
    return {
        "n": len(trades), "win_%": (trades["ret_net"] > 0).mean() * 100, "mean_R": trades["r_net"].mean(),
        "gross_R": trades["r_gross"].mean(), "sum_net_%": trades["ret_net"].sum() * 100,
        "PF": wins / losses if losses else np.inf,
    }


def barrier(path: MinutePath, i: int, side: int, entry: float, risk: float, horizon_min: int = 96 * 60,
            ks: tuple[float, ...] = (0.5, 1.0, 2.0), mfe_horizons: tuple[int, ...] = (60, 240, 1440)) -> dict[str, float]:
    """First passage to +kR vs -1R with no trailing (stop first on a same-minute tie), plus MFE/MAE in R."""
    end = min(i + horizon_min, path.run_end[i] + 1)
    hi, lo = path.high[i:end], path.low[i:end]
    fav, adv = (hi, lo) if side == 1 else (lo, hi)
    stop_hit = (lo <= entry - risk) if side == 1 else (hi >= entry + risk)
    s = int(np.argmax(stop_hit)) if stop_hit.any() else None
    out: dict[str, float] = {}
    for k in ks:
        hit = (fav >= entry + k * risk) if side == 1 else (fav <= entry - k * risk)
        t = int(np.argmax(hit)) if hit.any() else None
        if t is None and s is None:
            out[f"p{k}"] = np.nan
        elif t is None:
            out[f"p{k}"] = 0.0
        elif s is None:
            out[f"p{k}"] = 1.0
        else:
            out[f"p{k}"] = 1.0 if t < s else 0.0
    for h in mfe_horizons:
        f, a = fav[:h], adv[:h]
        out[f"mfe{h}"] = (f.max() - entry) * side / risk if side == 1 else (entry - f.min()) / risk
        out[f"mae{h}"] = (entry - a.min()) / risk if side == 1 else (a.max() - entry) / risk
    return out
