"""Why does the 15m order-block touch strategy lose, and does any defensible fix work?

    .venv/bin/python scripts/research_ob15_diagnosis.py decompose
    .venv/bin/python scripts/research_ob15_diagnosis.py features [--train-only]
    .venv/bin/python scripts/research_ob15_diagnosis.py candidates
    .venv/bin/python scripts/research_ob15_diagnosis.py all          # make ob15-diagnosis

Order of work matters for honesty: `decompose` and `features --train-only` were read first, the
candidate rules in HYPOTHESES were written down after that and frozen, and only then were the
test months (Jul-Oct) looked at, once, for the rules that passed the TRAIN gate (Jan-May).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from strategy.luxalgo_internal_ob import pine_internal_blocks, wilder_rma
from strategy.ob15_research import ExitSpec, FEE_ROUND_TRIP, barrier, eval_independent, summarize, walk_exit_variant
from strategy.ob_rejection import FEE_PER_SIDE, MinutePath, adx, aggregate, clean_minutes, ema, htf_trend, true_range
from strategy.ob_touch_15m import (EntryConfig, TrailConfig, build_entries, pine_touch_candidates, simulate,
                                   walk_trailing_exit)

ROOT = Path(__file__).resolve().parents[1]
MINUTE_DATA = ROOT / "data/parquet/BTCUSD_1m_20260101_20261026.parquet"
REPORTS = ROOT / "data/reports"
TEST_START = pd.Timestamp("2026-06-01", tz="UTC")
BAR = pd.Timedelta(minutes=15)
BASE_SPEC = ExitSpec(activate_r=1.0, trail_atr_mult=1.0)
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)


@dataclass
class Ctx:
    minutes: pd.DataFrame
    path: MinutePath
    bars: pd.DataFrame
    blocks: list
    visible: list
    entries: pd.DataFrame
    atr: np.ndarray


def load_ctx() -> Ctx:
    minutes = clean_minutes(pd.read_parquet(MINUTE_DATA))
    path = MinutePath(minutes)
    bars = aggregate(minutes, 15)
    blocks, visible = pine_internal_blocks(bars, 5)
    cfg = EntryConfig()
    entries = build_entries(pine_touch_candidates(bars, blocks, visible, cfg), path, cfg.entry_minutes)
    entries = entries.reset_index(drop=True)
    entries["idx"] = entries.index
    atr = wilder_rma(true_range(bars).fillna(bars["high"] - bars["low"]), 14).to_numpy(dtype=float)
    return Ctx(minutes, path, bars, blocks, visible, entries, atr)


def split(frame: pd.DataFrame, col: str = "entry_time") -> tuple[pd.DataFrame, pd.DataFrame]:
    when = pd.to_datetime(frame[col], utc=True)
    return frame[when < TEST_START], frame[when >= TEST_START]


def fmt(frame: pd.DataFrame, nd: int = 2) -> str:
    return frame.round(nd).to_string()


def random_pool(ctx: Ctx, entries: pd.DataFrame, n: int = 12000, seed: int = 7) -> pd.DataFrame:
    """Random-time entries with the same side mix and per-side stop-distance distribution as the real ones."""
    rng = np.random.default_rng(seed)
    path = ctx.path
    base = eval_independent(entries, path, BASE_SPEC)
    risk_by_side = {s: base.loc[base["side"] == s, "risk_%"].to_numpy() / 100 for s in (1, -1)}
    share_long = (base["side"] == 1).mean()
    lo = int(np.searchsorted(path.ns, pd.Timestamp("2026-01-05", tz="UTC").as_unit("ns").value))
    hi = len(path.ns) - 1500
    rows = []
    bar_close = ctx.bars.index.as_unit("ns").asi8
    for _ in range(n):
        i = int(rng.integers(lo, hi))
        side = 1 if rng.random() < share_long else -1
        entry = float(path.open[i])
        risk_frac = float(rng.choice(risk_by_side[side]))
        j = int(np.searchsorted(bar_close, path.ns[i], side="right")) - 1
        if j < 0 or not np.isfinite(ctx.atr[j]):
            continue
        rows.append({"entry_i": i, "side": side, "entry": entry, "atr": float(ctx.atr[j]),
                     "stop0": entry * (1 - side * risk_frac), "top": 0.0, "bottom": 0.0})
    pool = pd.DataFrame(rows)
    pool["idx"] = pool.index
    return pool


def decompose(ctx: Ctx) -> None:
    entries, path = ctx.entries, ctx.path
    print(f"entries (touch/near events on drawn 15m blocks): {len(entries)}")
    # validation: the flexible walker reproduces the production trailing walk exactly
    cfg = TrailConfig()
    bad = 0
    for r in entries.to_dict("records")[:400]:
        side, entry, atr = int(r["side"]), float(r["entry"]), float(r["atr"])
        stop0 = (r["bottom"] - cfg.stop_buffer_atr * atr) if side == 1 else (r["top"] + cfg.stop_buffer_atr * atr)
        if (entry - stop0) * side <= 0:
            continue
        a = walk_trailing_exit(path, int(r["entry_i"]), side, entry, stop0, atr, cfg)
        b = walk_exit_variant(path, int(r["entry_i"]), side, entry, stop0, atr, BASE_SPEC)
        bad += not (a[0] == b[0] and abs(a[1] - b[1]) < 1e-9 and a[2] == b[2])
    print(f"validation: walker vs production trailing walk mismatches in 400 entries = {bad} (should be 0)")

    print("\n=== 1a. FEE DRAG on the actual 682 one-at-a-time trades ===")
    trades = simulate(entries, path, cfg, FEE_PER_SIDE)
    f = FEE_PER_SIDE
    gross = (1 + trades["ret_net"]) / (1 - f) ** 2 - 1
    risk = trades["risk_%"] / 100
    r_gross, fee_r = gross / risk, (trades["ret_net"] - gross) / risk * -1
    tab = pd.DataFrame({
        "trades": [len(trades)], "avg_risk_%": [trades["risk_%"].mean()], "fee_per_trade_R": [fee_r.mean()],
        "gross_win_%": [(gross > 0).mean() * 100], "net_win_%": [(trades["ret_net"] > 0).mean() * 100],
        "gross_sumR": [r_gross.sum()], "net_sumR": [trades["r_net"].sum()],
        "gross_sum_%": [gross.sum() * 100], "net_sum_%": [trades["ret_net"].sum() * 100],
        "gross_PF": [gross[gross > 0].sum() / abs(gross[gross <= 0].sum())],
        "net_PF": [trades["ret_net"][trades["ret_net"] > 0].sum() / abs(trades["ret_net"][trades["ret_net"] <= 0].sum())],
    })
    print(fmt(tab.T, 3))
    trades.assign(ret_gross=gross, r_gross=r_gross).to_csv(REPORTS / "ob15_diagnosis_base_trades.csv", index=False)

    print("\n=== 1b. ENTRY QUALITY, no exit logic: P(+kR before -1R) vs RANDOM entries (same side mix, same stop distances) ===")
    pool = random_pool(ctx, entries)
    base_rows = eval_independent(entries, path, BASE_SPEC)[["idx"]]
    ob_rows = entries.merge(base_rows, on="idx")

    def barrier_table(rows: pd.DataFrame, stop_mode: str) -> pd.DataFrame:
        out = []
        for r in rows.to_dict("records"):
            side, entry = int(r["side"]), float(r["entry"])
            stop0 = r["stop0"] if stop_mode == "col" else ((r["bottom"] - 0.25 * r["atr"]) if side == 1 else (r["top"] + 0.25 * r["atr"]))
            risk_abs = (entry - stop0) * side
            out.append({"entry_time": ctx.path.index[int(r["entry_i"])], "side": side,
                        "fee_R": FEE_ROUND_TRIP * entry / risk_abs,
                        **barrier(ctx.path, int(r["entry_i"]), side, entry, risk_abs)})
        return pd.DataFrame(out)

    ob_b, rnd_b = barrier_table(ob_rows, "far"), barrier_table(pool, "col")
    ob_b.to_csv(REPORTS / "ob15_diagnosis_barrier_ob.csv", index=False)
    rows = []
    for name, b in (("order-block touch", ob_b), ("random entry", rnd_b)):
        for part, sub in (("all", b), ("train", split(b)[0]), ("test", split(b)[1])):
            res = {"set": name, "part": part, "n": len(sub), "fee_R": sub["fee_R"].mean()}
            for k in (0.5, 1.0, 2.0):
                res[f"P(+{k}R first)"] = sub[f"p{k}"].mean() * 100
                res[f"breakeven_{k}"] = ((1 + sub["fee_R"]) / (1 + k)).mean() * 100
            res["medMFE_1h"], res["medMAE_1h"] = sub["mfe60"].median(), sub["mae60"].median()
            res["medMFE_24h"], res["medMAE_24h"] = sub["mfe1440"].median(), sub["mae1440"].median()
            rows.append(res)
    print(fmt(pd.DataFrame(rows).set_index(["set", "part"]), 1))
    se = np.sqrt(ob_b["p1.0"].var() / len(ob_b) + rnd_b["p1.0"].var() / len(rnd_b)) * 100
    print(f"P(+1R first) difference OB minus random = {(ob_b['p1.0'].mean() - rnd_b['p1.0'].mean()) * 100:+.2f} pts (std err {se:.2f})")
    print("P(+kR first) is the chance the trade would have been at +kR before touching its stop. 'breakeven' is the chance needed to cover fees.")

    print("\n=== 1c. EXITS: same entries (each run on its own), different exits. mean_R is net of fees ===")
    specs = []
    for a in (0.5, 1.0, 1.5, 2.0):
        for m in (0.5, 1.0, 2.0, 3.0):
            specs.append(("trail", ExitSpec(activate_r=a, trail_atr_mult=m, label=f"trail act {a}R x{m}ATR")))
    for k in (0.5, 1.0, 2.0):
        specs.append(("target", ExitSpec(activate_r=None, target_r=k, label=f"fixed target {k}R")))
    for be in (0.5, 1.0):
        for m in (1.0, 2.0):
            specs.append(("breakeven", ExitSpec(activate_r=1.0, trail_atr_mult=m, be_r=be, label=f"BE at {be}R then trail x{m}")))
    for h in (60, 240, 1440, 5760):
        specs.append(("time", ExitSpec(activate_r=None, max_minutes=h, label=f"stop only, exit after {h // 60}h")))
    res = []
    pool_small = pool.iloc[:4000]
    for kind, spec in specs:
        t = eval_independent(entries, path, spec)
        s = summarize(t)
        tr, te = split(t)
        r_pool = summarize(eval_independent(pool_small, path, spec, "col"))
        res.append({"kind": kind, "exit": spec.label, "n": s["n"], "win_%": s["win_%"], "mean_R": s["mean_R"],
                    "gross_R": s["gross_R"], "PF": s["PF"], "train_R": summarize(tr)["mean_R"],
                    "test_R": summarize(te)["mean_R"], "random_R": r_pool["mean_R"]})
    grid = pd.DataFrame(res)
    grid.to_csv(REPORTS / "ob15_diagnosis_exit_grid.csv", index=False)
    print(grid.drop(columns="kind").round(3).to_string(index=False))
    print(f"best mean_R over {len(grid)} exits: {grid['mean_R'].max():+.3f}R (exit '{grid.loc[grid['mean_R'].idxmax(), 'exit']}'), "
          f"worst {grid['mean_R'].min():+.3f}R; random-entry mean_R range {grid['random_R'].min():+.3f} to {grid['random_R'].max():+.3f}")

    print("\n=== 1d. STOP PLACEMENT with the base trail (activate 1R, 1 ATR) ===")
    rows = []
    stops = [("far", b) for b in (0.0, 0.25, 0.5, 1.0, 1.5)] + [("near", 0.25), ("mid", 0.0)] + [("atr", m) for m in (0.5, 1.0, 1.5, 2.0, 3.0)]
    for mode, param in stops:
        t = eval_independent(entries, path, BASE_SPEC, mode, param)
        s = summarize(t)
        rows.append({"stop": f"{mode} {param}", "n": s["n"], "avg_risk_%": t["risk_%"].mean(), "win_%": s["win_%"],
                     "mean_R": s["mean_R"], "gross_R": s["gross_R"], "PF": s["PF"],
                     "stopped<=15m_%": (t["exit_reason"].eq("stop") & t["minutes"].le(15)).mean() * 100})
    print(pd.DataFrame(rows).round(3).to_string(index=False))
    t = eval_independent(entries, path, BASE_SPEC)
    t.to_csv(REPORTS / "ob15_diagnosis_base_independent.csv", index=False)
    losers = t[t["ret_net"] <= 0]
    print(f"base independent set n={len(t)}, losers={len(losers)} ({len(losers) / len(t) * 100:.0f}%); of losers: "
          f"<=5m {np.mean(losers['minutes'] <= 5) * 100:.0f}%, <=15m {np.mean(losers['minutes'] <= 15) * 100:.0f}%, "
          f"<=60m {np.mean(losers['minutes'] <= 60) * 100:.0f}%, >4h {np.mean(losers['minutes'] > 240) * 100:.0f}%")


def build_features(ctx: Ctx) -> pd.DataFrame:
    """Entry-time features. Every value comes from the last CLOSED 15m bar before the touch bar."""
    e, bars = ctx.entries, ctx.bars
    times = bars.index
    k = times.get_indexer(e["signal_time"])
    prior = k - 1
    assert (prior >= 0).all()
    assert (times[prior] <= e["entry_time"].to_numpy()).all(), "feature bar must close before the entry"
    close = bars["close"].to_numpy(dtype=float)
    atr_p = ctx.atr[prior]
    side = e["side"].to_numpy(dtype=float)
    e200 = ema(bars["close"], 200).to_numpy(dtype=float)
    ctx_htf = htf_trend(ctx.minutes, times).to_numpy()
    cols = list(htf_trend(ctx.minutes, times).columns)
    htf = pd.DataFrame(ctx_htf, columns=cols).iloc[prior].reset_index(drop=True)
    win = 672
    atr_pct = np.full(len(times), np.nan)
    w = np.lib.stride_tricks.sliding_window_view(ctx.atr, win)
    atr_pct[win - 1:] = np.nanmean(w <= w[:, -1:], axis=1)
    by_id = {b.block_id: b for b in ctx.blocks}
    near_blocks, choch = [], []
    for r, p in zip(e.to_dict("records"), prior):
        near_blocks.append(sum(1 for bid in ctx.visible[p] if bid != r["block_id"]
                               and abs((by_id[bid].top + by_id[bid].bottom) / 2 - r["entry"]) / r["entry"] < 0.01))
        prev = by_id.get(r["block_id"] - 1)
        choch.append(int(prev is not None and prev.bias != by_id[r["block_id"]].bias))
    hour = e["signal_time"].dt.hour
    f = pd.DataFrame({
        "idx": e["idx"], "entry_time": e["entry_time"], "side": e["side"],
        "zone_height_%": (e["top"] - e["bottom"]) / ((e["top"] + e["bottom"]) / 2) * 100,
        "zone_height_atr": (e["top"] - e["bottom"]) / atr_p,
        "zone_age_bars": ((e["signal_time"] - e["block_created_at"]) / BAR).astype(float),
        "entry_dist_%": np.where(e["side"] == 1, (e["entry"] - e["top"]) / e["top"], (e["bottom"] - e["entry"]) / e["bottom"]) * 100,
        "stop_dist_%": ((e["entry"] - np.where(e["side"] == 1, e["bottom"] - 0.25 * e["atr"], e["top"] + 0.25 * e["atr"])) * e["side"]) / e["entry"] * 100,
        "trend15_aligned": np.sign(close[prior] - e200[prior]) * side,
        "slope15_aligned_%": (e200[prior] - e200[prior - 16]) / e200[prior] * 100 * side,
        "trend1h_aligned": htf["h1_ema200_dir"].to_numpy() * side,
        "trend4h_aligned": htf["h4_ema200_dir"].to_numpy() * side,
        "h4_adx": htf["h4_adx"].to_numpy(),
        "into_zone_4bars_atr": -side * (close[prior] - close[prior - 4]) / atr_p,
        "into_zone_16bars_atr": -side * (close[prior] - close[prior - 16]) / atr_p,
        "session": np.select([hour < 8, hour < 13, hour < 21], ["asia 00-08", "europe 08-13", "us 13-21"], "late 21-24"),
        "weekend": (e["signal_time"].dt.dayofweek >= 5).astype(int),
        "atr_%": atr_p / e["entry"] * 100,
        "atr_pctile_7d": atr_pct[prior],
        "stacked_blocks_within_1%": near_blocks,
        "choch_like": choch,
    })
    f["bias"] = np.where(f["side"] == 1, "long", "short")
    return f


CONT = ["zone_height_%", "zone_height_atr", "zone_age_bars", "entry_dist_%", "stop_dist_%", "slope15_aligned_%", "h4_adx",
        "into_zone_4bars_atr", "into_zone_16bars_atr", "atr_%", "atr_pctile_7d"]
CAT = ["bias", "trend15_aligned", "trend1h_aligned", "trend4h_aligned", "session", "weekend", "stacked_blocks_within_1%", "choch_like"]


def feature_tables(ctx: Ctx, train_only: bool) -> pd.DataFrame:
    feats = build_features(ctx)
    outcome = eval_independent(ctx.entries, ctx.path, BASE_SPEC)[["idx", "ret_net", "r_net", "exit_reason", "minutes", "mfe_r"]]
    df = feats.merge(outcome, on="idx")
    df["win"] = (df["ret_net"] > 0).astype(int)
    tr, te = split(df)
    print(f"independent entries with the base exit: {len(df)} (train {len(tr)}, test {len(te)}); "
          f"overall mean_R train {tr['r_net'].mean():+.3f}" + ("" if train_only else f", test {te['r_net'].mean():+.3f}"))

    print("\n=== 2a. HOW LOSERS LOSE (base exit, all entries) ===")
    res = df.copy()
    loser = res["ret_net"] <= 0
    cls = np.select([
        ~loser,
        loser & res["exit_reason"].eq("stop") & res["minutes"].le(15),
        loser & res["exit_reason"].eq("stop") & res["mfe_r"].ge(0.5),
        loser & res["exit_reason"].eq("stop") & res["minutes"].gt(240),
        loser & res["exit_reason"].eq("stop") & res["mfe_r"].lt(0.25),
        loser & res["exit_reason"].eq("stop"),
        loser & res["exit_reason"].eq("trail_stop"),
    ], ["winner", "1 instant stop-out (<=15 min)", "2 worked >=0.5R then reversed to stop", "3 slow bleed (stop after >4h)",
        "4 never worked (MFE<0.25R)", "5 other stop", "6 trail exit that still lost (fees / ATR)"], "7 time/data exit")
    res["class"] = cls
    tab = res.groupby("class").agg(n=("r_net", "size"), share_pct=("r_net", lambda s: len(s) / len(res) * 100),
                                   mean_R=("r_net", "mean"), median_minutes=("minutes", "median"), mean_MFE_R=("mfe_r", "mean"))
    print(fmt(tab, 2))
    tab.to_csv(REPORTS / "ob15_diagnosis_failure_classes.csv")

    print("\n=== 2b. UNIVARIATE: win%, mean net R by entry-time feature (cut points from TRAIN quartiles) ===")
    rows = []
    overall = {"tr": tr["r_net"].mean(), "te": te["r_net"].mean()}
    for name in CONT + CAT:
        if name in CONT:
            edges = np.unique(np.nanquantile(tr[name], [0.25, 0.5, 0.75]))
            def binner(s: pd.Series) -> pd.Series:
                return pd.Series(np.digitize(s, edges), index=s.index)
            labels = {i: f"Q{i + 1}" + (f" (<{edges[0]:.3g})" if i == 0 else f" (>={edges[i - 1]:.3g})" if i == len(edges) else f" ({edges[i - 1]:.3g}-{edges[i]:.3g})") for i in range(len(edges) + 1)}
            btr, bte = binner(tr[name]), binner(te[name])
        else:
            btr = tr[name].astype(object).where(tr[name].notna(), 'na').astype(str)
            bte = te[name].astype(object).where(te[name].notna(), 'na').astype(str)
            labels = {v: v for v in sorted(set(btr) | set(bte))}
        for b in sorted(labels):
            m_tr, m_te = tr[btr == b], te[bte == b]
            row = {"feature": name, "bin": labels[b], "n_train": len(m_tr), "win_train": m_tr["win"].mean() * 100 if len(m_tr) else np.nan,
                   "R_train": m_tr["r_net"].mean() if len(m_tr) else np.nan}
            if not train_only:
                row.update({"n_test": len(m_te), "win_test": m_te["win"].mean() * 100 if len(m_te) else np.nan,
                            "R_test": m_te["r_net"].mean() if len(m_te) else np.nan})
                d_tr, d_te = row["R_train"] - overall["tr"], row["R_test"] - overall["te"]
                row["holds"] = "+" if d_tr > 0.05 and d_te > 0.05 else "-" if d_tr < -0.05 and d_te < -0.05 else "."
            rows.append(row)
    table = pd.DataFrame(rows)
    table.to_csv(REPORTS / ("ob15_diagnosis_features_train.csv" if train_only else "ob15_diagnosis_features.csv"), index=False)
    print(table.round(2).to_string(index=False))
    return df


# ---------------------------------------------------------------------------------------------
# Step 3. Candidate fixes. FROZEN before any test-month number was looked at; 10 hypotheses.
# Each is (name, plain-language rule, mask on the entry-time feature table or None, confirmation entry?)
# ---------------------------------------------------------------------------------------------
HYPOTHESES = [
    ("H1", "trade only with the 4h EMA200 side", lambda f: f["trend4h_aligned"] == 1, False),
    ("H2", "1h and 4h EMA200 both with the trade", lambda f: (f["trend1h_aligned"] == 1) & (f["trend4h_aligned"] == 1), False),
    ("H3", "validated-strategy regime: 15m EMA200 with the trade and 4h ADX <= 25", lambda f: (f["trend15_aligned"] == 1) & (f["h4_adx"] <= 25), False),
    ("H4", "fee-aware: skip stops tighter than 0.75% (fees <= ~0.16R)", lambda f: f["stop_dist_%"] >= 0.75, False),
    ("H5", "H1 and H4", lambda f: (f["trend4h_aligned"] == 1) & (f["stop_dist_%"] >= 0.75), False),
    ("H6", "rejection confirmation: touch bar closes back past the trigger, enter next bar open", None, True),
    ("H7", "H6 and 4h EMA200 with the trade", lambda f: f["trend4h_aligned"] == 1, True),
    ("H8", "price arrives after a >=1 ATR move toward the zone in the last 4 bars", lambda f: f["into_zone_4bars_atr"] >= 1.0, False),
    ("H9", "skip the Europe session 08-13 UTC (worst bucket in train)", lambda f: f["session"] != "europe 08-13", False),
    ("H10", "older zones only (>= 13 bars, 3h+)", lambda f: f["zone_age_bars"] >= 13, False),
]
GATE = {"n_train": 40, "mean_R": 0.0, "PF": 1.15, "random_p": 0.10}
SURVIVE = {"n_test": 25, "n_total": 60, "mean_R": 0.0, "PF": 1.10, "random_p": 0.05, "months_up": 2}


def confirmation_entries(ctx: Ctx, entries: pd.DataFrame) -> pd.DataFrame:
    """Re-enter each touch only if its bar closed back past the trigger; fill at the next bar's first minute."""
    bars, path = ctx.bars, ctx.path
    close = bars["close"].to_numpy(dtype=float)
    rows = []
    for r in entries.to_dict("records"):
        k = bars.index.get_loc(r["signal_time"])
        ok = close[k] >= r["trigger_level"] if r["side"] == 1 else close[k] <= r["trigger_level"]
        if not ok:
            continue
        i = path.start(bars.index[k])
        if i >= len(path.ns) or path.ns[i] != bars.index[k].as_unit("ns").value:
            continue
        assert path.index[i] >= bars.index[k], "confirmation entry must come after the touch bar closed"
        rows.append({**r, "entry_i": i, "entry_time": path.index[i], "entry": float(path.open[i])})
    return pd.DataFrame(rows)


def matched_random_p(rule: pd.DataFrame, pool: pd.DataFrame, pool_r: np.ndarray, n_draw: int = 2000, seed: int = 11) -> float:
    """Chance that random entries with the same side and similar stop distance match the rule's mean net R."""
    rng = np.random.default_rng(seed)
    pool_risk = pool["risk_%"].to_numpy()
    pool_side = pool["side"].to_numpy()
    cands = []
    for side, risk in zip(rule["side_i"], rule["risk_%"]):
        ok = np.flatnonzero((pool_side == side) & (np.abs(pool_risk / risk - 1) < 0.15))
        cands.append(ok if len(ok) else np.flatnonzero(pool_side == side))
    draws = np.array([[pool_r[rng.choice(c)] for c in cands] for _ in range(n_draw)]).mean(axis=1)
    return float((draws >= rule["r_net"].mean()).mean())


def dollars(trades: pd.DataFrame, capital: float = 200.0, leverage: float = 10.0) -> tuple[float, int | None]:
    bal, wiped = capital, None
    for i, x in enumerate(trades.sort_values("exit_time")["ret_net"], 1):
        if bal <= 0:
            break
        bal = max(0.0, bal + capital * leverage * x)
        if bal == 0:
            wiped = i
    return bal, wiped


def run_candidates(ctx: Ctx) -> None:
    feats = build_features(ctx).set_index("idx")
    pool = random_pool(ctx, ctx.entries)
    pool_eval = eval_independent(pool, ctx.path, BASE_SPEC, "col")
    pool_eval["side_i"] = pool_eval["side"]
    pool_idx = pool_eval["idx"].to_numpy()
    pool_r = pool_eval["r_net"].to_numpy()
    cfg = TrailConfig()

    def run(entries_h: pd.DataFrame) -> pd.DataFrame:
        trades = simulate(entries_h, ctx.path, cfg, FEE_PER_SIDE) if not entries_h.empty else pd.DataFrame()
        if not trades.empty:
            trades["side_i"] = np.where(trades["side"] == "long", 1, -1)
        return trades

    def stats(trades: pd.DataFrame) -> dict[str, float]:
        if trades.empty:
            return {"n": 0, "win_%": np.nan, "mean_R": np.nan, "PF": np.nan, "net_%": 0.0}
        w, l = trades.loc[trades["ret_net"] > 0, "ret_net"].sum(), abs(trades.loc[trades["ret_net"] <= 0, "ret_net"].sum())
        return {"n": len(trades), "win_%": (trades["ret_net"] > 0).mean() * 100, "mean_R": trades["r_net"].mean(),
                "PF": w / l if l else np.inf, "net_%": trades["ret_net"].sum() * 100}

    rows, kept = [], {}
    base = run(ctx.entries)
    for name, text, mask, confirm in [("BASE", "all touches (reference)", None, False)] + HYPOTHESES:
        entries_h = confirmation_entries(ctx, ctx.entries) if confirm else ctx.entries
        if mask is not None:
            entries_h = entries_h[mask(feats.loc[entries_h["idx"]]).to_numpy()]
        trades = run(entries_h)
        tr, te = split(trades) if not trades.empty else (trades, trades)
        s_tr = stats(tr)
        s_tr["random_p"] = matched_random_p(tr, pool_eval, pool_r) if len(tr) >= 10 else np.nan
        kept[name] = (text, trades, tr, te, s_tr)
        rows.append({"rule": name, "what": text[:62], **{f"train_{k}": v for k, v in s_tr.items()}})
    table = pd.DataFrame(rows)
    table.to_csv(REPORTS / "ob15_diagnosis_candidates_train.csv", index=False)
    print(f"=== 3a. TRAIN (Jan-May) only: {len(HYPOTHESES)} hypotheses, plus the unfiltered base ===")
    print(table.round(2).to_string(index=False))

    gate_ok = [n for n, (_, _, _, _, s) in kept.items() if n != "BASE" and s["n"] >= GATE["n_train"] and s["mean_R"] > GATE["mean_R"]
               and s["PF"] >= GATE["PF"] and s["random_p"] <= GATE["random_p"]]
    eligible = {n: v for n, v in kept.items() if n != "BASE" and v[4]["n"] >= GATE["n_train"]}
    chosen = gate_ok or ([max(eligible, key=lambda n: eligible[n][4]["mean_R"])] if eligible else [])
    print(f"\nTrain gate (n>={GATE['n_train']}, mean_R>0, PF>={GATE['PF']}, matched-random p<={GATE['random_p']}): passed = {gate_ok or 'none'}")
    if not gate_ok and chosen:
        print(f"No rule passed the gate; the best train mean_R among rules with enough trades ({chosen[0]}) is evaluated on test once, only for the record.")

    print("\n=== 3b. TEST (Jul-Oct), evaluated once for the chosen rule(s) ===")
    out = []
    for name in chosen:
        text, trades, tr, te, s_tr = kept[name]
        s_te = stats(te)
        s_te["random_p"] = matched_random_p(te, pool_eval, pool_r) if len(te) >= 10 else np.nan
        months = te.assign(m=pd.to_datetime(te["entry_time"], utc=True).dt.strftime("%Y-%m")).groupby("m").agg(
            n=("ret_net", "size"), win=("ret_net", lambda s: (s > 0).mean() * 100), net=("ret_net", lambda s: s.sum() * 100))
        months = months[months["n"] >= 8]
        months_up = int((months["net"] > 0).sum())
        survived = (s_te["n"] >= SURVIVE["n_test"] and s_te["n"] + s_tr["n"] >= SURVIVE["n_total"] and s_te["mean_R"] > 0
                    and s_te["PF"] >= SURVIVE["PF"] and s_te["random_p"] <= SURVIVE["random_p"] and months_up >= SURVIVE["months_up"])
        bal_all, wiped_all = dollars(trades)
        bal_te, wiped_te = dollars(te)
        out.append({"rule": name, "what": text, "train_n": s_tr["n"], "train_mean_R": s_tr["mean_R"], "test_n": s_te["n"],
                    "test_win_%": s_te["win_%"], "test_mean_R": s_te["mean_R"], "test_PF": s_te["PF"], "test_net_%": s_te["net_%"],
                    "test_random_p": s_te["random_p"], "months_up/months": f"{months_up}/{len(months)}",
                    "$200_10x_all_months": round(bal_all, 0), "$200_10x_test_only": round(bal_te, 0), "SURVIVES": survived})
        print(months.round(1).to_string())
    result = pd.DataFrame(out)
    result.to_csv(REPORTS / "ob15_diagnosis_candidates_test.csv", index=False)
    print(result.round(3).T.to_string() if len(result) else "(nothing eligible)")
    base_tr, base_te = split(base)
    print(f"\nReference, unfiltered: train mean_R {base_tr['r_net'].mean():+.3f} (n={len(base_tr)}), test mean_R {base_te['r_net'].mean():+.3f} (n={len(base_te)})")
    print(f"Hypotheses tested: {len(HYPOTHESES)} filters (plus 27 exits, 13 stop placements and ~70 feature bins looked at before)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["decompose", "features", "candidates", "all"])
    parser.add_argument("--train-only", action="store_true")
    args = parser.parse_args()
    REPORTS.mkdir(parents=True, exist_ok=True)
    ctx = load_ctx()
    if args.stage in ("decompose", "all"):
        decompose(ctx)
    if args.stage in ("features", "all"):
        feature_tables(ctx, args.train_only)
    if args.stage in ("candidates", "all"):
        run_candidates(ctx)


if __name__ == "__main__":
    main()
