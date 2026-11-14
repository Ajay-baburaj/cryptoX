"""Stage 2 analysis. Reads stage2_* and selection.json, writes CSV tables to results/."""
import json, math, pickle, statistics as st
import numpy as np, pandas as pd
from common import RES, load_binance, bars
from protocol import *
from sim import metrics

M = pd.read_csv(RES / "stage2_metrics.csv")
M1 = pd.read_csv(RES / "stage1_metrics.csv")
TR = pickle.load(open(RES / "stage2_trades.pkl", "rb"))
SEL = json.loads((RES / "selection.json").read_text())
KEY = ["tf", "preset", "label", "zone", "stars", "exit", "buffer"]
N_ALL = M.drop_duplicates(KEY).shape[0]
print("variants", N_ALL)
bl = (M.zone == "all") & (M.stars == "all") & (M.exit == "R1.0") & (M.buffer == .25) & (M.label == "primary")
# stage reproducibility: dev/val unchanged after full-data rerun
j = M[M.split.isin(["dev", "val"])].merge(M1, on=KEY + ["split", "cost"], suffixes=("", "_1"))
print("stage1 vs stage2 max |avgR diff|", np.nanmax(np.abs(j.avgR - j.avgR_1)), "rows", len(j))

M[bl & (M.cost == "base")].to_csv(RES / "baseline_splits.csv", index=False)
M[bl].pivot_table(index=["tf", "preset", "cost"], columns="split", values="avgR").to_csv(RES / "baseline_costs.csv")
b = M[(M.exit == "R1.0") & (M.buffer == .25) & (M.label == "primary") & (M.cost == "base")]
b.to_csv(RES / "cube_R1_b025.csv", index=False)
M[(M.zone == "all") & (M.stars == "all") & (M.label == "primary") & (M.cost == "base")].to_csv(RES / "exits_all.csv", index=False)
M[(M.label != "primary") & (M.cost == "base")].to_csv(RES / "sensitivity.csv", index=False)


def key_of(row, split):
    return (int(row["tf"]), row["preset"], row.get("label", "primary"), row["zone"], str(row["stars"]), row["exit"], float(row["buffer"]), split)


def z_p(R):
    if len(R) < 3 or R.std(ddof=1) == 0:
        return np.nan
    t = R.mean() / (R.std(ddof=1) / math.sqrt(len(R)))
    return .5 * math.erfc(t / math.sqrt(2))


def boot(entry, R, B=4000, seed=7):
    """Calendar-week block bootstrap of mean R; inactive weeks carry no trades."""
    if len(R) < 5:
        return np.nan, np.nan
    wk = pd.to_datetime(entry).to_period("W").astype(str).values
    weeks, inv = np.unique(wk, return_inverse=True)
    sums, cnts = np.bincount(inv, R), np.bincount(inv)
    rng = np.random.default_rng(seed)
    draw = rng.integers(0, len(weeks), (B, len(weeks)))
    m = sums[draw].sum(1) / np.maximum(cnts[draw].sum(1), 1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def trades(row, splits):
    a = [TR[key_of(row, s)] for s in splits if key_of(row, s) in TR]
    if not a:
        return dict(entry=np.array([], "datetime64[ns]"), R=np.array([]), stopf=np.array([]), side=np.array([], int), why=np.array([], int))
    return {k: np.concatenate([x[k] for x in a]) for k in ("entry", "R", "stopf", "side", "why")}


# DSR on selection evidence (dev+val) with all N trials
def trial_srs():
    d = M[(M.cost == "base") & M.split.isin(["dev", "val"])]
    out = []
    for k, g in d.groupby(KEY, sort=False):
        pass
    return out


rows = []
keys = [k for k in TR if k[7] == "dev"]
srs, pv = [], []
for k in keys:
    k2 = k[:7]
    R = np.concatenate([TR[k2 + (s,)]["R"] for s in ("dev", "val") if k2 + (s,) in TR])
    if len(R) >= 30 and R.std() > 0:
        srs.append(R.mean() / R.std(ddof=1))
        pv.append((k2, z_p(R), len(R), R.mean()))
var_sr = float(np.var(srs, ddof=1))
g = 0.5772156649


def sr_star(N, var):
    nd = st.NormalDist()
    return math.sqrt(var) * ((1 - g) * nd.inv_cdf(1 - 1 / N) + g * nd.inv_cdf(1 - 1 / (N * math.e)))


def dsr(R, N, var):
    n = len(R)
    sr = R.mean() / R.std(ddof=1)
    s = ((R - R.mean()) ** 3).mean() / R.std() ** 3
    k = ((R - R.mean()) ** 4).mean() / R.std() ** 4
    z = (sr - sr_star(N, var)) * math.sqrt(n - 1) / math.sqrt(max(1 - s * sr + (k - 1) / 4 * sr ** 2, 1e-9))
    return float(st.NormalDist().cdf(z)), sr, sr_star(N, var)


ps = np.array([x[1] for x in pv])
o = np.argsort(ps); m = len(ps)
bh = ps[o] <= .05 * (np.arange(m) + 1) / m
nbh = int(np.flatnonzero(bh).max() + 1) if bh.any() else 0
print(json.dumps(dict(dev_val_tested=m, raw_p05=int((ps < .05).sum()), bh_passing=nbh, bonf_passing=int((ps < .05 / N_ALL).sum()),
                      min_p=float(np.nanmin(ps)), bonf_threshold=.05 / N_ALL, trial_sr_var=var_sr, sr_star_N=sr_star(N_ALL, var_sr)), indent=1))

# Selected and baseline: per split + bootstrap + DSR
out = []
def report(tag, row):
    for sp in ("dev", "val", "test"):
        t = trades(row, [sp])
        R = t["R"]
        lo, hi = boot(t["entry"], R)
        mt = metrics(R, t["stopf"])
        out.append(dict(tag=tag, split=sp, **mt, ci_lo=lo, ci_hi=hi, p_gt0=z_p(R)))
    t = trades(row, ["dev", "val"])
    if len(t["R"]) > 30:
        d, sr, ss = dsr(t["R"], N_ALL, var_sr)
        out.append(dict(tag=tag, split="DSR(dev+val)", trades=len(t["R"]), avgR=sr, win=ss, ret=d))


for tf in TIMEFRAMES:
    for p in PRESETS:
        report(f"baseline_{tf}m_{p}", dict(tf=tf, preset=p, label="primary", zone="all", stars="all", exit="R1.0", buffer=.25))
    s = SEL[str(tf)]
    if s:
        report(f"selected_{tf}m", dict(s, label="primary"))
pd.DataFrame(out).to_csv(RES / "baseline_selected_ci.csv", index=False)

# Holm across test hypotheses (selected + baseline, test split)
f = pd.DataFrame(out); tst = f[f.split == "test"].dropna(subset=["p_gt0"]).sort_values("p_gt0")
mm = len(tst); adj = (tst.p_gt0.values * (mm - np.arange(mm))).clip(max=1)
tst = tst.assign(holm=np.maximum.accumulate(adj)); tst.to_csv(RES / "test_holm.csv", index=False)

# Walk-forward: every quarter pick best primary variant on trailing 12m, trade next quarter
prim = {}
for k, v in TR.items():
    if k[2] == "primary":
        prim.setdefault(k[:7], []).append(v)
prim = {k: {f: np.concatenate([x[f] for x in v]) for f in ("entry", "R", "stopf", "side")} for k, v in prim.items()}
folds = pd.date_range("2025-01-01", "2026-11-01", freq="QS")
if folds[-1] < pd.Timestamp("2026-11-01"):
    folds = folds.append(pd.DatetimeIndex(["2026-11-01"]))
wf, wf_all = [], []
for scope in TIMEFRAMES + ["ALL"]:
    oos = []
    for a, b in zip(folds[:-1], folds[1:]):
        tr0 = np.datetime64(a - pd.DateOffset(months=12)); a64, b64 = np.datetime64(a), np.datetime64(b)
        best, bv = None, 0
        for k, v in prim.items():
            if scope != "ALL" and k[0] != scope:
                continue
            mk = (v["entry"] >= tr0) & (v["entry"] < a64)
            if mk.sum() >= 30:
                x = v["R"][mk].mean()
                if x > bv:
                    best, bv = k, x
        if best is None:
            wf_all.append(dict(scope=scope, fold=str(a.date()), pick=None, train=None, n=0, oosR=None))
            continue
        v = prim[best]; mk = (v["entry"] >= a64) & (v["entry"] < b64)
        oos.append({f: v[f][mk] for f in v})
        wf_all.append(dict(scope=scope, fold=str(a.date()), pick=str(best), train=bv, n=int(mk.sum()), oosR=float(v["R"][mk].mean()) if mk.sum() else None))
    if oos:
        z = {f: np.concatenate([x[f] for x in oos]) for f in ("entry", "R", "stopf", "side")}
        lo, hi = boot(z["entry"], z["R"])
        wf.append(dict(scope=scope, **metrics(z["R"], z["stopf"]), ci_lo=lo, ci_hi=hi, p_gt0=z_p(z["R"])))
    else:
        wf.append(dict(scope=scope, trades=0))
pd.DataFrame(wf).to_csv(RES / "walkforward.csv", index=False); pd.DataFrame(wf_all).to_csv(RES / "walkforward_folds.csv", index=False)

# Side / year / regime for baseline and selected (causal daily regime)
m, _ = load_binance()
d = bars(m, 1440)
sma = d.close.rolling(200).mean().shift(1)
rv = d.close.pct_change().rolling(20).std().shift(1)
rvm = rv.rolling(180).median().shift(1)
reg = pd.DataFrame({"trend": np.where((d.close.shift(1) >= sma), "bull", "bear"), "vol": np.where(rv >= rvm, "hi", "lo")}, index=d.index)
reg.loc[sma.isna(), "trend"] = "na"; reg.loc[rvm.isna(), "vol"] = "na"
rows = []
def slice_tbl(tag, row):
    t = trades(row, ["dev", "val", "test"])
    if len(t["R"]) == 0:
        return
    et = pd.to_datetime(t["entry"], utc=True)
    days = et.floor("D")
    r = reg.reindex(days)
    for name, mk in [("long", t["side"] == 1), ("short", t["side"] == -1)] + [(str(y), et.year.values == y) for y in (2024, 2025, 2026)] + \
            [("bull", r.trend.values == "bull"), ("bear", r.trend.values == "bear"), ("hi_vol", r.vol.values == "hi"), ("lo_vol", r.vol.values == "lo")]:
        for rg, sub in [("all", np.ones(len(mk), bool)), ("test2026", et.year.values == 2026)]:
            k = mk & sub
            lo, hi = boot(t["entry"][k], t["R"][k], B=1000)
            rows.append(dict(tag=tag, cut=name, scope=rg, **metrics(t["R"][k], t["stopf"][k]), ci_lo=lo, ci_hi=hi))
for tf in TIMEFRAMES:
    for p in PRESETS:
        slice_tbl(f"baseline_{tf}m_{p}", dict(tf=tf, preset=p, label="primary", zone="all", stars="all", exit="R1.0", buffer=.25))
    s = SEL[str(tf)]
    if s:
        slice_tbl(f"selected_{tf}m", dict(s, label="primary"))
pd.DataFrame(rows).to_csv(RES / "slices.csv", index=False)

# Primary-grid diagnostics: how many variants positive by split at base cost, zero cost
for cost in ("zero", "maker_entry", "base"):
    p = M[(M.label == "primary") & (M.cost == cost) & (M.trades >= 30)].pivot_table(index=["tf","preset","zone","stars","exit","buffer"], columns="split", values="avgR")
    print(cost, "variants with >=30 trades; share avgR>0:", p.gt(0).mean().round(3).to_dict(), "both dev&val&test>0:", int((p > 0).all(axis=1).sum()), "of", len(p))
p = M[(M.label == "primary") & (M.cost == "base") & (M.trades >= 20)].pivot_table(index=["tf","preset","zone","stars","exit","buffer"], columns="split", values="avgR").dropna()
print("rank corr dev-val, val-test:", round(p.dev.rank().corr(p.val.rank()), 3), round(p.val.rank().corr(p.test.rank()), 3))
print(M[bl & (M.cost == "base")][["tf", "preset", "split", "trades", "win", "avgR", "pf", "mdd", "ret"]].round(3).to_string())
print(pd.DataFrame(out).round(3).to_string())
print(pd.DataFrame(wf).round(3).to_string())
print(tst.round(4).to_string())
