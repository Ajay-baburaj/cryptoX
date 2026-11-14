"""`make volume-orderflow`: rebuild taker-flow minutes and run the frozen protocol once."""
import io, json, multiprocessing as mp, sys, zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from research.volume_orderflow import (COST, DAY, STRESS_COST, Market, bars30, cvd_signals, funding_signals,
                                       level_trades, quarter_signals, sequential_holds, window_levels)

DATA = ROOT / 'data/binance_ob_timeframes'
OUT = ROOT / 'research/volume_orderflow/output'
START = pd.Timestamp('2023-11-01', tz='UTC')
HOLDOUT = pd.Timestamp('2025-07-01', tz='UTC')
DEV = pd.Timestamp('2024-01-01', tz='UTC')
COLS = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume', 'count',
        'taker_buy_volume', 'taker_buy_quote_volume', 'ignore']


def load() -> Market:
    frames = []
    for path in sorted((DATA / 'raw').glob('BTCUSDT-1m-*.zip')):
        with zipfile.ZipFile(path) as z, z.open(z.namelist()[0]) as f:
            first = f.read(1)
            data = first + f.read()
        frames.append(pd.read_csv(io.BytesIO(data), header=0 if first == b'o' else None, names=COLS))
    frame = pd.concat(frames)
    repair = json.loads((DATA / 'gap_20261028_rest.json').read_text())
    frame = pd.concat([frame, pd.DataFrame(repair, columns=COLS)]).astype({c: float for c in COLS[1:6] + COLS[9:10]})
    frame['open_time'] = frame['open_time'].astype('int64')
    frame = frame.drop_duplicates('open_time').sort_values('open_time')
    expected = int(START.timestamp() * 1000) + 60000 * np.arange(len(frame))
    if not (frame.open_time.to_numpy() == expected).all():
        raise SystemExit('Minutes are not contiguous from 2023-11-01')
    if (frame.taker_buy_volume > frame.volume + 1e-9).any():
        raise SystemExit('Taker-buy volume exceeds volume')
    funding = np.zeros(len(frame))
    f = pd.read_parquet(DATA / 'funding.parquet')
    stamps = pd.to_datetime(f['calc_time'] if 'calc_time' in f else f['time'], utc=True, unit=None if f['calc_time'].dtype.kind == 'M' else 'ms')
    index = ((stamps - START).dt.total_seconds() // 60).astype(int).to_numpy()
    keep = (index >= 0) & (index < len(funding))
    funding[index[keep]] = f['last_funding_rate'].astype(float).to_numpy()[keep]
    print('minutes', len(frame), 'funding events', int((funding != 0).sum()))
    return Market(*[frame[c].to_numpy(float) for c in ('open', 'high', 'low', 'close', 'volume', 'taker_buy_volume')], funding)


m: Market
bars, levels = None, {}
ANCHORS = {'00:00': 0, '08:00': 480, '13:30': 810}
LEVEL_RULES = [('80pct', 'eighty', {}), ('80pct_wide', 'eighty', {'min_width': .01}), ('va_rejection', 'va_rejection', {}),
               ('poc_reversion', 'poc_reversion', {}), ('naked_poc_1R', 'naked_poc', {'reward': 1.}),
               ('naked_poc_2R', 'naked_poc', {'reward': 2.}), ('balance_breakout', 'balance_breakout', {})]


def variants():
    out = {}
    for name, rule, params in LEVEL_RULES:
        for label in ANCHORS:
            out[f'{name}@{label}'] = ('level', rule, label, params)
    for kind in ('first_minute', 'hour_decile'):
        for hours in (4, 8, 12):
            out[f'quarter_{kind}_{hours}h'] = ('event', quarter_signals, (kind,), hours)
    for kind in ('z', 'abs'):
        for hours in (8, 24):
            out[f'funding_{kind}_{hours}h'] = ('event', funding_signals, (kind,), hours)
    out['cvd_divergence'] = ('event', cvd_signals, (False,), 3)
    out['cvd_divergence_vpin'] = ('event', cvd_signals, (True,), 3)
    return out


def run(spec, seed=None):
    if spec[0] == 'level':
        _, rule, label, params = spec
        shifts = None
        if seed is not None:
            rng = np.random.default_rng(seed)
            width = levels[label][:, 2] - levels[label][:, 1]
            shifts = rng.choice([-1, 1], len(width)) * rng.uniform(.5, 1.5, len(width)) * width
        result = level_trades(m, bars, levels[label], ANCHORS[label], rule, params, shifts)
    else:
        _, fn, args, hours = spec
        signals = CACHE[(fn.__name__, args)]
        if seed is not None:
            rng = np.random.default_rng(seed)
            moved = [(i + int(rng.choice([-1, 1])) * int(rng.integers(1, 31)) * DAY, s) for i, s in signals]
            signals = sorted((i, s) for i, s in moved if 0 <= i < len(m.o))
        result = sequential_holds(m, signals, hours * 60)
    return np.array(result, float).reshape(-1, 2)


CACHE = {}


def split(trades):
    time = START + pd.to_timedelta(trades[:, 0], unit='min')
    return time, np.asarray((time >= HOLDOUT)), np.asarray((time >= DEV) & (time < HOLDOUT))


def summary(trades, name):
    time, hold, dev = split(trades)
    h, d, gross = trades[hold, 1], trades[dev, 1], trades[:, 1]
    full_net = gross - COST
    net = h - COST
    t = net.mean() / net.std(ddof=1) * np.sqrt(len(net)) if len(net) > 2 and net.std() > 0 else 0.
    trimmed = np.sort(net)[:-max(1, len(net) // 100)] if len(net) else net
    years = {y: full_net[np.asarray(time.year == y)] for y in (2024, 2025, 2026)}
    return {'variant': name, 'hold_n': len(h), 'hold_gross_bps': h.mean() * 1e4 if len(h) else np.nan,
            'hold_net_bps': net.mean() * 1e4 if len(h) else np.nan, 'hold_net20_bps': (h - STRESS_COST).mean() * 1e4 if len(h) else np.nan,
            'hold_t': t, 'hold_win_pct': (net > 0).mean() * 100 if len(h) else np.nan, 'hold_total_pct': net.sum() * 100,
            'dev_n': len(d), 'dev_net_bps': (d - COST).mean() * 1e4 if len(d) else np.nan,
            **{f'net_{y}_bps': v.mean() * 1e4 if len(v) else np.nan for y, v in years.items()},
            'trimmed_net_bps': trimmed.mean() * 1e4 if len(trimmed) else np.nan}


def placebo_one(args):
    name, seed = args
    trades = run(SPECS[name], seed)
    if not len(trades):
        return np.nan
    _, hold, _ = split(trades)
    return (trades[hold, 1] - COST).mean() * 1e4 if hold.any() else np.nan


def main():
    global m, bars, SPECS
    m = load()
    bars = bars30(m)
    for label, anchor in ANCHORS.items():
        levels[label] = window_levels(m, anchor)
    SPECS = variants()
    for spec in SPECS.values():
        if spec[0] == 'event' and (spec[1].__name__, spec[2]) not in CACHE:
            CACHE[(spec[1].__name__, spec[2])] = spec[1](m, *spec[2])
    rows = [summary(run(spec), name) for name, spec in SPECS.items()]
    table = pd.DataFrame(rows).set_index('variant')
    table['placebo_runs'], table['placebo_pct'] = 0, np.nan
    ctx = mp.get_context('fork')
    with ctx.Pool() as pool:
        for name in table.index[table.hold_net_bps > 0]:
            runs = 1000 if table.loc[name, 'hold_t'] >= 3.3 else 300
            values = np.array(pool.map(placebo_one, [(name, s) for s in range(runs)], chunksize=10))
            values = values[~np.isnan(values)]
            table.loc[name, 'placebo_runs'] = len(values)
            table.loc[name, 'placebo_pct'] = (values < table.loc[name, 'hold_net_bps']).mean() * 100
    gross_ok = ~table.index.str.startswith('quarter') | (table.hold_gross_bps >= 28)
    table['pass'] = ((table.hold_net_bps > 0) & (table.hold_net20_bps > 0) & (table.hold_t >= 3.3) & (table.hold_n >= 100)
                     & (table[['net_2024_bps', 'net_2025_bps', 'net_2026_bps']] > 0).all(axis=1) & (table.trimmed_net_bps > 0)
                     & (table.dev_net_bps > 0) & gross_ok & (table.placebo_pct > 95))
    OUT.mkdir(parents=True, exist_ok=True)
    table.round(2).to_csv(OUT / 'results.csv')
    pd.set_option('display.width', 250, 'display.max_columns', 30)
    print(table.round(1)[['hold_n', 'hold_gross_bps', 'hold_net_bps', 'hold_t', 'hold_win_pct', 'hold_total_pct', 'dev_n', 'dev_net_bps',
                          'net_2024_bps', 'net_2025_bps', 'net_2026_bps', 'placebo_runs', 'placebo_pct', 'pass']].to_string())
    print('variants passing all gates:', int(table['pass'].sum()), 'of', len(table))


if __name__ == '__main__':
    main()
