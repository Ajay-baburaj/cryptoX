"""Development run (train+validation only). Test bars are not loaded. Freezes finalists."""
import json, sys, time
from pipeline import *


def main():
    t0 = time.time()
    m, f = load_binance(DEV_END)
    assert m.index.max() < pd.Timestamp(DEV_END, tz="UTC")
    tables = run_grid(m, f)
    var = all_variant_rows(tables, "base")
    rows, weekly = [], {}
    weeks = pd.period_range(TRAIN[0], "2025-12-31", freq="W").astype(str)
    for v in var:
        t = v["trades"]; row = {k: v[k] for k in ("htf", "ltf", "preset", "flt", "exit")}
        for lab, (a, b) in dict(train=TRAIN, val=VAL).items():
            x = t[period_mask(t, a, b)]
            for k, val in stats(x.R.values).items():
                row[f"{lab}_{k}"] = val
        t_dev = t[period_mask(t, TRAIN[0], DEV_END)]
        row["dev_mean"] = t_dev.R.mean() if len(t_dev) else np.nan
        row["dev_n"] = len(t_dev)
        rows.append(row)
        wk = t_dev.time.dt.tz_localize(None).dt.to_period("W").astype(str)
        weekly[len(rows) - 1] = t_dev.groupby(wk).R.sum().reindex(weeks, fill_value=0.).values
    df = pd.DataFrame(rows)
    OUT.mkdir(exist_ok=True)
    df.to_csv(OUT / "dev_all_variants.csv", index=False)
    # Selection: frozen rule from config.py
    ok = df[(df.train_n >= SELECT_MIN_TRAIN) & (df.val_n >= SELECT_MIN_VAL) & (df.train_mean > 0) & (df.val_mean > 0)].copy()
    ok["score"] = ok[["train_mean", "val_mean"]].min(axis=1)
    fin = ok.sort_values("score", ascending=False).groupby(["htf", "ltf"]).head(1)
    fin.to_csv(OUT / "finalists.csv", index=False)
    # Multiple testing on the development sample (weekly net R, circular 4-week block bootstrap).
    M = np.vstack([weekly[i] for i in sorted(weekly)])
    keep = df.dev_n.values >= 20
    M = M[keep]; idx = df.index[keep]
    rng = np.random.default_rng(11)
    nw, nb, B = M.shape[1], 3000, 4
    start = rng.integers(0, nw, (nb, nw // B + 1))
    wi = (np.repeat(start, B, 1) + np.tile(np.arange(B), start.shape[1])) % nw
    wi = wi[:, :nw]
    obs, centre = M.mean(1), M.mean(1)
    # White reality check on mean weekly R; also studentized.
    bm = M[:, wi].mean(2) - centre[:, None]
    se = bm.std(1, ddof=1)
    t_obs = obs / np.where(se > 0, se, np.nan)
    rc = float((bm.max(0) >= obs.max()).mean())
    rc_t = float((np.nanmax(bm / se[:, None], 0) >= np.nanmax(t_obs)).mean())
    from statistics import NormalDist
    p = np.array([1 - NormalDist().cdf(x) if np.isfinite(x) else 1.0 for x in t_obs])
    o = np.argsort(p); bh = np.minimum.accumulate((p[o] * len(p) / np.arange(1, len(p) + 1))[::-1])[::-1]
    q = np.empty_like(bh); q[o] = bh
    d2 = df.loc[idx, ["htf", "ltf", "preset", "flt", "exit", "dev_n", "dev_mean", "train_n", "train_mean", "val_n", "val_mean"]].copy()
    d2["weekly_mean_R"] = obs; d2["t"] = t_obs; d2["p"] = p; d2["bh_q"] = q
    d2.sort_values("t", ascending=False).to_csv(OUT / "dev_multiple_testing.csv", index=False)
    summ = dict(n_variants=int(len(df)), n_tested_in_mt=int(keep.sum()), best_weekly_mean=float(obs.max()),
                white_rc_p=rc, studentized_max_t_p=rc_t, n_bh_q_lt_10pct=int((q < .10).sum()),
                n_pass_selection=int(len(ok)), n_finalists=int(len(fin)),
                sec=round(time.time() - t0))
    json.dump(summ, open(OUT / "dev_summary.json", "w"), indent=1)
    print(json.dumps(summ, indent=1))
    print(fin[["htf", "ltf", "preset", "flt", "exit", "train_n", "train_mean", "val_n", "val_mean"]].to_string())


if __name__ == "__main__":
    main()
