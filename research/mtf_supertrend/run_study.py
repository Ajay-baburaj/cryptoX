"""MTF Supertrend retest on BTC. Protocol frozen before any outcome was computed (2026-11-09).

Data:   Binance USD-M BTCUSDT perp 1m, resampled. Warmup 2023-11/12; TRAIN 2024; VAL 2025; TEST 2026-01..10.
        `dev` physically truncates data at 2026-01-01. Delta BTCUSD 2026 is a replication only (it has gaps).
Grid:   7 LTF/HTF pairs x LTF factor {2,3,4} x exit {trail, 2R, 50% partial at 1R} x ADX {off,20,25}
        x direction {both,long}. = 378 variants. ATR 10, HTF factor 3, all 7 days (crypto).
Costs:  base 0.07% per side (0.05 taker + 0.02 slip) + actual funding. Also zero and the script default 0.03.
Select: per pair, TRAIN n>=30, VAL n>=15, mean net return > 0 in both; highest min(train,val).
Test:   finalists + the script-default rule for each pair (ATR10x3, trail, both). Holm over all of them.
Returns are per-trade % of notional at 1x, unlevered and uncompounded.
"""
import json
import math
import sys
from dataclasses import asdict
from itertools import product
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mtf_supertrend as ms  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)
MIN = ROOT / "data/binance_ob_timeframes/minutes.parquet"
FUND = ROOT / "data/binance_ob_timeframes/funding.parquet"
DELTA = ROOT / "data/parquet/BTCUSD_1m_20260101_20261026.parquet"
PERIODS = {"train": ("2024-01-01", "2025-01-01"), "val": ("2025-01-01", "2026-01-01"),
           "test": ("2026-01-01", "2026-11-01")}
PAIRS = [("5min", "1h"), ("5min", "4h"), ("15min", "1h"), ("15min", "4h"), ("1h", "4h"), ("1h", "1D"), ("4h", "1D")]
BASE, SCRIPT = 0.14, 0.06  # round-trip %

GRID = [dict(ltf=l, htf=h, factor=f, exit=e, adx=a, dir=d) for (l, h), f, e, a, d in
        product(PAIRS, [2.0, 3.0, 4.0], ["trail", "rr2", "partial"], [0, 20, 25], ["both", "long"])]
_cache, _end, _source = {}, None, "binance"


def init(end, source):
    global _end, _source
    _end, _source = end, source


def bars(ltf):
    if ltf not in _cache:
        d = pd.read_parquet(DELTA if _source == "delta" else MIN)[["open", "high", "low", "close"]]
        if _end:
            d = d[d.index < pd.Timestamp(_end, tz="UTC")]
        _cache[ltf] = d.resample(ltf, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return _cache[ltf]


def cfg_of(v):
    c = ms.Config(htf=v["htf"], factor=v["factor"], trade_dir=v["dir"], qty_step=0.001, commission_pct=0.0,
                  slippage=0.0, trade_days=set(range(7)))
    if v["exit"] == "rr2":
        c.use_tp, c.rr = True, 2.0
    if v["exit"] == "partial":
        c.use_partial, c.partial_rr, c.partial_pct = True, 1.0, 50.0
    if v["adx"]:
        c.use_adx, c.adx_thr = True, float(v["adx"])
    return c


def trades_of(v):
    """Gross per-trade % return at 1x, entered at time t, with funding cost % already computed."""
    t, _, _ = ms.backtest(bars(v["ltf"]), cfg_of(v))
    if t.empty:
        return pd.DataFrame(columns=["entry_time", "side", "gross", "funding"])
    f = pd.read_parquet(FUND)
    ft, fr = f["time"].to_numpy(dtype="datetime64[ns]"), f["last_funding_rate"].to_numpy(float) * 100
    cum = np.concatenate([[0.0], fr.cumsum()])
    a = np.searchsorted(ft, t["entry_time"].to_numpy(dtype="datetime64[ns]"), side="right")
    b = np.searchsorted(ft, t["exit_time"].to_numpy(dtype="datetime64[ns]"), side="right")
    sgn = np.where(t["side"] == "long", 1.0, -1.0)
    return pd.DataFrame({"entry_time": t["entry_time"], "side": t["side"],
                         "gross": 100 * t["pnl"] / (t["qty"] * t["entry"]), "funding": sgn * (cum[b] - cum[a])})


def stats(t, rt=BASE):
    if len(t) == 0:
        return dict(n=0, mean=np.nan, win=np.nan, pf=np.nan, total=0.0, dd=0.0)
    r = (t["gross"] - t["funding"] - rt).to_numpy()
    eq = r.cumsum()
    dd = (np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max()
    loss = -r[r <= 0].sum()
    return dict(n=len(r), mean=r.mean(), win=100 * (r > 0).mean(), pf=r[r > 0].sum() / loss if loss else np.inf,
                total=r.sum(), dd=dd)


def slice_(t, p):
    a, b = (pd.Timestamp(x, tz="UTC") for x in PERIODS[p])
    return t[(t["entry_time"] >= a) & (t["entry_time"] < b)]


def p_mean_gt0(r):
    if len(r) < 3 or r.std(ddof=1) == 0:
        return 1.0
    return 0.5 * math.erfc((r.mean() / (r.std(ddof=1) / math.sqrt(len(r)))) / math.sqrt(2))


def work(args):
    v, periods = args
    t = trades_of(v)
    row = dict(v)
    for p in periods:
        s = stats(slice_(t, p))
        row.update({f"{p}_{k}": x for k, x in s.items()})
        row[f"{p}_gross"] = stats(slice_(t, p), 0)["mean"]
    dv = pd.concat([slice_(t, p) for p in ("train", "val")])
    row["dev_p"] = p_mean_gt0((dv["gross"] - dv["funding"] - BASE).to_numpy())
    return row


def bh(ps):
    ps = np.asarray(ps)
    o = np.argsort(ps)
    q = ps[o] * len(ps) / np.arange(1, len(ps) + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(len(ps))
    out[o] = np.minimum(q, 1)
    return out


def run_grid(end, periods, source="binance", grid=GRID):
    with Pool(8, initializer=init, initargs=(end, source)) as p:
        return pd.DataFrame(p.map(work, [(v, periods) for v in grid], chunksize=4))


def dev():
    r = run_grid("2026-01-01", ["train", "val"])
    r["bh_q"] = bh(r["dev_p"].fillna(1))
    r.to_csv(OUT / "dev_grid.csv", index=False)
    ok = r[(r.train_n >= 30) & (r.val_n >= 15) & (r.train_mean > 0) & (r.val_mean > 0)].copy()
    ok["score"] = ok[["train_mean", "val_mean"]].min(axis=1)
    fin = ok.sort_values("score", ascending=False).groupby(["ltf", "htf"], sort=False).head(1)
    keys = ["ltf", "htf", "factor", "exit", "adx", "dir"]
    json.dump(fin[keys].to_dict("records"), open(OUT / "finalists.json", "w"), indent=1)
    print(f"variants {len(r)}; pass rule {len(ok)}; min dev p {r.dev_p.min():.4f}; BH q<.10: {(r.bh_q < .1).sum()}")
    print("positive by pair (train&val):", ok.groupby(['ltf', 'htf']).size().to_dict())
    print(r.groupby(["ltf", "htf"], sort=False)[["train_mean", "val_mean", "train_gross", "val_gross"]].median().round(3))
    print(fin[keys + ["train_n", "train_mean", "val_n", "val_mean", "dev_p"]].round(3).to_string(index=False))


def boot(r, n=5000):
    g = np.random.default_rng(7)
    m = r[g.integers(0, len(r), (n, len(r)))].mean(axis=1)
    return np.percentile(m, [2.5, 97.5])


def test():
    finals = [dict(v, role="finalist") for v in json.load(open(OUT / "finalists.json"))]
    defaults = [dict(ltf=l, htf=h, factor=3.0, exit="trail", adx=0, dir="both", role="default") for l, h in PAIRS]
    rules = finals + defaults
    init(None, "binance")
    rows = []
    for v in rules:
        t = trades_of(v)
        te = slice_(t, "test")
        r = (te["gross"] - te["funding"] - BASE).to_numpy()
        s = stats(te)
        lo, hi = boot(r) if len(r) > 2 else (np.nan, np.nan)
        m = pd.Series(r, index=pd.DatetimeIndex(te["entry_time"]).tz_localize(None)).resample("MS").sum() if len(r) else pd.Series(dtype=float)
        tr, va = stats(slice_(t, "train")), stats(slice_(t, "val"))
        rows.append(dict(v, tr_mean=tr["mean"], tr_total=tr["total"], va_mean=va["mean"], va_total=va["total"], n=s["n"],
                         win=s["win"], mean=s["mean"], lo=lo, hi=hi, pf=s["pf"], total=s["total"], dd=s["dd"],
                         mean0=stats(te, 0)["mean"], total_script=stats(te, SCRIPT)["total"],
                         long=stats(te[te.side == "long"])["mean"], short=stats(te[te.side == "short"])["mean"],
                         mon_pos=f"{int((m > 0).sum())}/{len(m)}", p=p_mean_gt0(r)))
    x = pd.DataFrame(rows)
    o = np.argsort(x.p.to_numpy())
    h = np.maximum.accumulate([min(1, x.p.iloc[j] * (len(x) - i)) for i, j in enumerate(o)])
    x.loc[x.index[o], "holm"] = h
    x.to_csv(OUT / "holdout.csv", index=False)
    pd.set_option("display.width", 250)
    print(x.drop(columns=["p"]).round(3).to_string(index=False))

    full = run_grid(None, ["train", "val", "test"])
    full.to_csv(OUT / "full_grid.csv", index=False)
    a = full[(full.train_mean > 0) & (full.val_mean > 0) & (full.test_mean > 0)]
    print(f"\ngrid all-3-periods positive: {len(a)}/{len(full)}; test mean>0: {(full.test_mean > 0).sum()}")
    print(a[["ltf", "htf", "factor", "exit", "adx", "dir", "train_n", "train_mean", "val_mean", "test_n", "test_mean"]].round(3).to_string(index=False))
    print(full.groupby(["ltf", "htf"], sort=False)[["train_mean", "val_mean", "test_mean", "test_gross"]].median().round(3))
    print(full.groupby("exit")[["train_mean", "val_mean", "test_mean"]].median().round(3))
    print(full.groupby("dir")[["train_mean", "val_mean", "test_mean"]].median().round(3))
    print(full.groupby("adx")[["train_mean", "val_mean", "test_mean"]].median().round(3))
    m = pd.read_parquet(MIN)["close"]
    for p, (a_, b_) in PERIODS.items():
        s = m[(m.index >= pd.Timestamp(a_, tz="UTC")) & (m.index < pd.Timestamp(b_, tz="UTC"))]
        print(f"buy&hold {p}: {100 * (s.iloc[-1] / s.iloc[0] - 1):.1f}%")
    d = run_grid(None, ["test"], "delta", rules_strip(rules))
    d.to_csv(OUT / "delta_replication.csv", index=False)
    print("\nDelta 2026 replication (no funding row match; gaps):")
    print(d[["ltf", "htf", "factor", "exit", "adx", "dir", "test_n", "test_mean", "test_total", "test_gross"]].round(3).to_string(index=False))


def rules_strip(rules):
    return [{k: v for k, v in r.items() if k != "role"} for r in rules]


def lookahead():
    init(None, "binance")
    b = bars("15min")
    cfg = ms.Config(htf="4h", trade_days=set(range(7)), use_adx=True)
    bad = 0
    full = ms.build_signals(b, cfg)
    for cut in np.linspace(3000, len(b) - 10, 8).astype(int):
        tr = ms.build_signals(b.iloc[:cut], cfg)
        for c in ("long_sig", "short_sig"):
            bad += int((tr[c].to_numpy() != full[c].iloc[:cut].to_numpy()).sum())
    print("lookahead mismatches:", bad)


if __name__ == "__main__":
    {"dev": dev, "test": test, "lookahead": lookahead}[sys.argv[1]]()
