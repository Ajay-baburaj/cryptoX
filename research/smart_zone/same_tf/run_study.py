"""Usage: run_study.py 1   (dev+val only, minutes truncated at 2026-01-01, writes selection.json)
          run_study.py 2   (full data; refuses unless selection.json exists)"""
import sys, json, pickle
import numpy as np, pandas as pd
from multiprocessing import Pool
from dataclasses import replace
from common import load_binance, bars, funding_cum, RES
from protocol import *
from smart_zone import compute_signals, preset
from sim import Walk, sim_all, sequential, net_r, metrics

SENS = {
    "pivot3": dict(left=3, right=3), "pivot8": dict(left=8, right=8), "pivot10_5": dict(left=10, right=5),
    "merge_0.3": dict(merge_frac=.3), "merge_0.8": dict(merge_frac=.8),
    "pad_0.05": dict(pad_atr=.05), "pad_0.2": dict(pad_atr=.2),
    "hl_100": dict(recency_hl=100.), "hl_400": dict(recency_hl=400.),
    "flipgap_5": dict(flip_gap=5), "flipgap_20": dict(flip_gap=20), "flipbonus_0.5": dict(flip_bonus=.5),
    "depth_.05": dict(min_depth=.05), "depth_.2": dict(min_depth=.2),
    "beyond_0": dict(max_beyond=0.), "beyond_.5": dict(max_beyond=.5),
    "margin_0": dict(margin=0.), "margin_.15": dict(margin=.15),
    "reaction_exc": dict(reaction="excursion"), "filter_strength": dict(filter_on="strength"),
    "prev_outside": dict(prev_outside=True), "invalidate_1atr": dict(invalidate_atr=1.),
    "maxpiv_15": dict(max_pivots=15), "maxpiv_60": dict(max_pivots=60),
}
G = {}


def init(end):
    m, f = load_binance(end)
    G.update(m=m, w=Walk(*[m[c].values for c in ("open", "high", "low", "close")], funding_cum(m.index, f)))


def split_bounds(index):
    out = {}
    for k, (a, b) in SPLITS.items():
        A, B = index.searchsorted(pd.Timestamp(a, tz="UTC")), index.searchsorted(pd.Timestamp(b, tz="UTC"))
        if A < len(index):
            out[k] = (A, B - 1)
    return out


def make_signals(tf, p, m):
    df = bars(m, tf)
    sig = compute_signals(*[df[c].values for c in ("open", "high", "low", "close")], p)
    keep = sig["i"].astype(int) + 1 < len(df) if len(sig["i"]) else np.zeros(0, bool)
    sig = {k: v[keep] for k, v in sig.items()}
    sig["i"] = sig["i"].astype(int)
    ent = m.index.searchsorted(df.index[sig["i"] + 1])
    sig["t"] = df.index[sig["i"]].values
    return df, sig, ent


def subset(sig, zone, star):
    k = sig["kind"]
    mask = np.ones(len(k), bool) if zone == "all" else (k == "sup") if zone == "sup" else (k == "res") if zone == "res" else np.isin(k, ["SR", "RS"])
    if star != "all":
        mask &= sig["stars"] == star
    return mask


def job(a):
    tf, pname, label, over = a
    m, w = G["m"], G["w"]
    p = preset(pname, **over)
    df, sig, ent = make_signals(tf, p, m)
    bounds = split_bounds(m.index)
    # order by entry, then strongest
    ord_ = np.lexsort((-sig["score"], ent))
    sig = {k: v[ord_] for k, v in sig.items()}; ent = ent[ord_]
    cap = np.full(len(ent), -1)
    split = np.full(len(ent), "", dtype=object)
    for k, (A, B) in bounds.items():
        mk = (ent >= A) & (ent <= B)
        cap[mk], split[mk] = B, k
    primary = label == "primary"
    exits = EXITS if primary else [("R", 1.)]
    bufs = STOP_BUFFERS if primary else [.25]
    zs, ss = (ZONE_SETS, STAR_SETS) if primary else (["all"], ["all"])
    rows, trades = [], {}
    valid = cap >= 0
    for ex in exits:
        ename = f"{ex[0]}{'' if ex[1] is None else ex[1]}"
        for b in bufs:
            s = sim_all(w, sig, ent, cap, tf, ex, b)
            for z in zs:
                for st in ss:
                    mk = subset(sig, z, st) & s["ok"] & valid
                    for sp in bounds:
                        ix = np.flatnonzero(mk & (split == sp))
                        ix = sequential(ent, s["x"], ix)
                        key = (tf, pname, label, z, str(st), ename, b, sp)
                        for cn, cost in COSTS.items():
                            R, sf = net_r(w, sig, ent, s, ix, cost)
                            rows.append(dict(tf=tf, preset=pname, label=label, zone=z, stars=str(st), exit=ename, buffer=b, split=sp, cost=cn, **metrics(R, sf)))
                            if cn == "base":
                                trades[key] = dict(entry=m.index.values[ent[ix]], R=R, stopf=sf, side=sig["side"][ix].astype(int), why=s["why"][ix],
                                                   kind=sig["kind"][ix], stars=sig["stars"][ix])
    return rows, trades, dict(tf=tf, preset=pname, label=label, signals=len(ent), bars=len(df))


if __name__ == "__main__":
    stage = int(sys.argv[1])
    end = "2026-01-01" if stage == 1 else None
    if stage == 2 and not (RES / "selection.json").exists():
        sys.exit("run stage 1 first")
    jobs = [(tf, n, "primary", {}) for tf in TIMEFRAMES for n in PRESETS]
    jobs += [(tf, n, k, v) for k, v in SENS.items() for tf in TIMEFRAMES for n in PRESETS]
    with Pool(7, init, (end,)) as pool:
        res = pool.map(job, jobs, chunksize=1)
    rows = pd.DataFrame([r for x in res for r in x[0]])
    tr = {k: v for x in res for k, v in x[1].items()}
    rows.to_csv(RES / f"stage{stage}_metrics.csv", index=False)
    pd.DataFrame([x[2] for x in res]).to_csv(RES / f"stage{stage}_jobs.csv", index=False)
    with open(RES / f"stage{stage}_trades.pkl", "wb") as fh:
        pickle.dump(tr, fh)
    print("rows", len(rows), "n trades-keys", len(tr), "variants", rows.drop_duplicates(["tf","preset","label","zone","stars","exit","buffer"]).shape[0])
    if stage == 1:
        d = rows[(rows.cost == "base") & (rows.label == "primary")]
        keys = ["tf", "preset", "zone", "stars", "exit", "buffer"]
        a = d[d.split == "dev"].merge(d[d.split == "val"], on=keys, suffixes=("_dev", "_val"))
        a = a[(a.trades_dev >= MIN_DEV) & (a.trades_val >= MIN_VAL) & (a.avgR_dev > 0) & (a.avgR_val > 0)]
        a["score"] = a[["avgR_dev", "avgR_val"]].min(axis=1)
        sel = {}
        for tf in TIMEFRAMES:
            b = a[a.tf == tf].sort_values("score", ascending=False)
            sel[str(tf)] = None if b.empty else b.iloc[0][keys + ["trades_dev", "trades_val", "avgR_dev", "avgR_val"]].to_dict()
        sel["n_passing_per_tf"] = a.groupby("tf").size().to_dict()
        sel["n_passing_per_tf"] = {str(k): int(v) for k, v in sel["n_passing_per_tf"].items()}
        (RES / "selection.json").write_text(json.dumps(sel, indent=1, default=float))
        print(json.dumps(sel, indent=1, default=float))
