"""Post-freeze evaluation. Finalists come from results/finalists.csv (written by run_dev.py); nothing is selected here."""
import json, time
from pipeline import *
from dataclasses import asdict


def key(r):
    return (r.htf, r.ltf, r.preset), r.flt, r.exit


def split_stats(t, costs=("base",)):
    out = {}
    for lab, (a, b) in dict(train=TRAIN, val=VAL, test=TEST).items():
        x = t[period_mask(t, a, b)]
        for c in costs:
            R = S.net_R(x, c)
            for k, v in stats(R).items():
                out[f"{lab}_{k}" + ("" if c == "base" else f"_{c}")] = v
    return out


def holm(p):
    p = np.asarray(p, float); o = np.argsort(p); m = len(p)
    adj = np.maximum.accumulate((m - np.arange(m)) * p[o]).clip(max=1)
    r = np.empty(m); r[o] = adj
    return r


def null_test(tab_s, trades, mm, ex, nb=400, seed=3):
    """Random-entry null over the test trades' months/sides; same risk% and exit geometry; base costs."""
    rng = np.random.default_rng(seed)
    t = trades
    if len(t) < 5:
        return np.nan, np.nan, np.nan
    obs = S.net_R(t, "base").mean()
    mon = pd.DatetimeIndex(pd.to_datetime(mm.ts, utc=True)).strftime("%Y-%m").values
    pos = {k: np.flatnonzero(mon == k) for k in np.unique(t.time.dt.strftime("%Y-%m").values)}
    tmon = t.time.dt.strftime("%Y-%m").values
    means = []
    for _ in range(nb):
        rs = []
        for j, (mo, side, ep, risk) in enumerate(zip(tmon, t.side.values, t.ep.values, t.risk.values)):
            i = int(rng.choice(pos[mo][:-1]))
            e = mm.o[i]; rk = risk / ep * e
            stop = e - side * rk
            target, trail = None, None
            if ex in S.KR:
                target = e + side * S.KR[ex] * rk
            elif ex == "atr_trail":
                trail = (rk, rk)  # ATR proxy: 1 risk distance
            else:
                target = e + side * 1.5 * rk
            res = S.run_exit(mm, i, int(side), stop, target, trail)
            if res is None:
                continue
            xi, xp = res
            g = (xp - e) * side / rk
            f = (mm.fund[xi] - mm.fund[i]) * side * e / rk
            rs.append(g - (0.0007 * e + 0.0007 * xp) / rk - f)
        means.append(np.mean(rs))
    means = np.array(means)
    return obs, means.mean(), float((means >= obs).mean())


def main():
    t0 = time.time()
    OUT.mkdir(exist_ok=True)
    m, f = load_binance(None)
    tables = run_grid(m, f)
    mm = S.Minutes(m, f)
    S_all = all_variant_rows(tables, "base")
    # All-variants table for every period (post-freeze distribution, not selection).
    rows = []
    for v in S_all:
        r = {k: v[k] for k in ("htf", "ltf", "preset", "flt", "exit")}
        r.update(split_stats(v["trades"], ("base", "maker_entry", "zero")))
        rows.append(r)
    A = pd.DataFrame(rows); A.to_csv(OUT / "all_variants_all_periods.csv", index=False)
    fin = pd.read_csv(OUT / "finalists.csv")
    sel = [(r.htf, r.ltf, r.preset, r.flt, r.exit, "finalist") for r in fin.itertuples()]
    sel += [(*b, "baseline") for b in BASELINES]
    rep, mon, sid = [], [], []
    for h, l, p, flt, ex, src in sel:
        t = variant_trades(tables, (h, l, p), flt, ex)
        t = t.assign(R=S.net_R(t, "base"))
        d = dict(htf=h, ltf=l, preset=p, flt=flt, exit=ex, source=src)
        d.update(split_stats(t, ("base", "base_gst", "maker_entry", "zero")))
        tt = t[period_mask(t, *TEST)]
        d.update(zip(("test_mean_boot", "test_lo", "test_hi", "test_p_le0"), boot_mean_ci(tt)))
        dv = t[~period_mask(t, *TEST)]
        d.update(zip(("dev_mean_boot", "dev_lo", "dev_hi", "dev_p_le0"), boot_mean_ci(dv)))
        d.update(zip(("null_obs", "null_mean", "null_p"), null_test(None, tt, mm, ex)))
        rep.append(d)
        for lab, x in (("test", tt), ("all", t)):
            if len(x):
                g = x.groupby(x.time.dt.tz_localize(None).dt.to_period("M").astype(str)).R
                for mo, ser in g:
                    mon.append(dict(h=h, l=l, p=p, flt=flt, ex=ex, set=lab, month=mo, n=len(ser), meanR=ser.mean(), sumR=ser.sum()))
        for lab, x in (("dev", dv), ("test", tt)):
            for side, ser in x.groupby("side").R:
                sid.append(dict(h=h, l=l, p=p, flt=flt, ex=ex, set=lab, side=int(side), n=len(ser), meanR=ser.mean(), wr=(ser > 0).mean()))
    R = pd.DataFrame(rep)
    R["test_p_holm"] = holm(R.test_p_le0.fillna(1).values)
    R.to_csv(OUT / "finalists_baselines.csv", index=False)
    pd.DataFrame(mon).to_csv(OUT / "monthly.csv", index=False)
    pd.DataFrame(sid).to_csv(OUT / "sides.csv", index=False)
    # Marginal filter / exit value, paired across combo x preset x exit (or filter).
    rows = []
    idx = ["htf", "ltf", "preset", "exit"]
    base = A[A.flt == "none"].set_index(idx)
    for flt in FILTERS[1:]:
        cur = A[A.flt == flt].set_index(idx)
        for per in ("train", "val", "test"):
            j = cur[[f"{per}_mean", f"{per}_n"]].join(base[[f"{per}_mean", f"{per}_n"]], rsuffix="_b", how="inner").dropna()
            j = j[(j[f"{per}_n"] >= 15)]
            rows.append(dict(filter=flt, period=per, cells=len(j), mean_delta_R=(j[f"{per}_mean"] - j[f"{per}_mean_b"]).mean(),
                             share_cells_better=float((j[f"{per}_mean"] > j[f"{per}_mean_b"]).mean()),
                             share_filtered_cells_positive=float((j[f"{per}_mean"] > 0).mean())))
    pd.DataFrame(rows).to_csv(OUT / "filter_marginals.csv", index=False)
    idx = ["htf", "ltf", "preset", "flt"]
    base = A[A.exit == "fixed_1R"].set_index(idx)
    rows = []
    for ex in EXITS:
        cur = A[A.exit == ex]
        for per in ("train", "val", "test"):
            c = cur[cur[f"{per}_n"] >= 15]
            rows.append(dict(exit=ex, period=per, cells=len(c), mean_R=c[f"{per}_mean"].mean(), share_positive=float((c[f"{per}_mean"] > 0).mean())))
    pd.DataFrame(rows).to_csv(OUT / "exit_marginals.csv", index=False)
    # Walk-forward: choose best-by-train-mean variant (n>=30) in rolling 12m, trade next 6m.
    wins = [("2024-01-01", "2025-01-01", "2025-01-01", "2025-07-01"), ("2024-07-01", "2025-07-01", "2025-07-01", "2026-01-01"),
            ("2025-01-01", "2026-01-01", "2026-01-01", "2026-07-01"), ("2025-07-01", "2026-07-01", "2026-07-01", "2026-11-01")]
    wf_rows, wf_R = [], []
    for ta, tb, oa, ob in wins:
        best, bm = None, -9
        for v in S_all:
            x = v["trades"]; x = x[period_mask(x, ta, tb)]
            if len(x) >= 30 and x.R.mean() > bm:
                best, bm = v, x.R.mean()
        o = best["trades"]; o = o[period_mask(o, oa, ob)]
        wf_rows.append(dict(train=f"{ta}..{tb}", oos=f"{oa}..{ob}", pick=f'{best["htf"]}/{best["ltf"]}/{best["preset"]}/{best["flt"]}/{best["exit"]}',
                            train_mean=bm, oos_n=len(o), oos_mean=o.R.mean() if len(o) else np.nan, oos_sum=o.R.sum()))
        wf_R.append(o)
    wf = pd.concat(wf_R).sort_values("time")
    wf_sum = dict(n=int(len(wf)), mean=float(wf.R.mean()), sum=float(wf.R.sum()))
    if len(wf):
        wf_sum.update(zip(("m", "lo", "hi", "p_le0"), boot_mean_ci(wf)))
    pd.DataFrame(wf_rows).to_csv(OUT / "walkforward.csv", index=False)
    json.dump(wf_sum, open(OUT / "walkforward_summary.json", "w"), indent=1)
    # Assumption sensitivity on the seven tested rules (reporting only, no re-selection).
    combs = sorted({(h, l) for h, l, *_ in sel})
    sens = []
    for name, cfg in SENS.items():
        tb = run_grid(m, f, combos=combs, cfg=cfg, procs=7)
        for h, l, p, flt, ex, src in sel:
            if (h, l, p) not in tb or tb[(h, l, p)][0].empty:
                continue
            t = variant_trades(tb, (h, l, p), flt, ex)
            if t.empty:
                continue
            t = t.assign(R=S.net_R(t, "base"))
            d = dict(cfg=name, htf=h, ltf=l, preset=p, flt=flt, exit=ex)
            for lab, (a, b) in dict(dev=(TRAIN[0], DEV_END), test=TEST).items():
                x = t[period_mask(t, a, b)]
                d[f"{lab}_n"], d[f"{lab}_mean"] = len(x), x.R.mean() if len(x) else np.nan
            sens.append(d)
    S2 = pd.DataFrame(sens); S2.to_csv(OUT / "sensitivity.csv", index=False)
    # Delta BTCUSD 2026 replication of the seven rules (2026 only; heavy gaps; no funding; warmup inside Jan).
    d = pd.read_parquet(DELTA_1M)
    tbd = run_grid(d, None, combos=combs, procs=7)
    delta = []
    for h, l, p, flt, ex, src in sel:
        if tbd.get((h, l, p), (pd.DataFrame(),))[0].empty:
            continue
        t = variant_trades(tbd, (h, l, p), flt, ex)
        if len(t):
            t = t.assign(R=S.net_R(t, "base")); s = stats(t.R.values)
            delta.append(dict(htf=h, ltf=l, preset=p, flt=flt, exit=ex, source=src, **s, **dict(zip(("m", "lo", "hi", "p"), boot_mean_ci(t)))))
    pd.DataFrame(delta).to_csv(OUT / "delta_replication.csv", index=False)
    print("sec", round(time.time() - t0))


if __name__ == "__main__":
    main()
