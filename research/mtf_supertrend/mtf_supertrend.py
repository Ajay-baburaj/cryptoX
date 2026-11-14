"""
MTF Supertrend strategy — Python backtester
===========================================
Same rules as mtf_supertrend_strategy.pine:

  Long : higher-TF Supertrend green AND current-TF Supertrend flips red -> green
  Short: higher-TF Supertrend red   AND current-TF Supertrend flips green -> red
  Optional: higher-TF flip as entry (current TF must already agree)
  Optional: ADX filter, session / date / weekday filters
  Stop : trailing stop = current-TF Supertrend line
  TP   : optional R:R target, optional partial TP
  Size : default % of equity, or fixed risk % per trade (optional compounding)

Execution model (matches TradingView defaults):
  * Signals are evaluated on bar close, orders fill at the NEXT bar's open.
  * Stop/limit levels set at bar close are active on the next bar.
  * Gaps through a stop/target fill at the open.
  * If stop and target are both inside one bar, the path is assumed
    O->H->L->C when the open is nearer the high, else O->L->H->C (TV's rule).
  * Higher-TF Supertrend uses only the last CLOSED higher-TF candle (no repaint).

Usage
-----
  pip install pandas numpy            (plus yfinance if you use --yf)

  # From a CSV with columns: datetime,open,high,low,close[,volume]
  python mtf_supertrend.py --csv data.csv --htf 1h

  # From Yahoo Finance (free, limited intraday history)
  python mtf_supertrend.py --yf ^NSEI --interval 15m --period 60d --htf 1h --htf-offset 15min

NSE note: Indian sessions start at 09:15, so pass --htf-offset 15min to make
1h candles 09:15-10:15, 10:15-11:15 ... like TradingView.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


# ───────────────────────── Config ─────────────────────────
@dataclass
class Config:
    # Supertrend
    atr_len: int = 10
    factor: float = 3.0
    htf: str = "1h"              # pandas offset alias: "1h", "4h", "1D", ...
    htf_offset: str | None = None  # e.g. "15min" for NSE 09:15 alignment
    htf_atr_len: int = 10
    htf_factor: float = 3.0

    # Signals
    trade_dir: str = "both"      # "long", "short", "both"
    trade_htf_flip: bool = False
    use_adx: bool = False
    adx_len: int = 14
    adx_thr: float = 20.0

    # Take profit
    use_tp: bool = False
    rr: float = 2.0
    use_partial: bool = False
    partial_rr: float = 1.0
    partial_pct: float = 50.0

    # Sizing
    initial_capital: float = 100_000.0
    default_pct_equity: float = 100.0
    use_risk: bool = False
    risk_pct: float = 1.0
    use_compound: bool = False
    qty_step: float = 1.0        # 1 for shares/lots, 0.001 for crypto
    point_value: float = 1.0

    # Costs
    commission_pct: float = 0.03  # per side, % of traded value
    slippage: float = 0.0         # price units added against you per fill

    # Time filters
    use_session: bool = False
    session_start: str = "09:15"
    session_end: str = "15:00"
    start_date: str | None = None
    end_date: str | None = None
    trade_days: set[int] = field(default_factory=lambda: {0, 1, 2, 3, 4})  # Mon=0


# ───────────────────────── Indicators ─────────────────────────
def rma(s: pd.Series, length: int) -> pd.Series:
    """Wilder's moving average, seeded with an SMA like TradingView's ta.rma."""
    v = s.to_numpy(dtype=float)
    out = np.full(len(v), np.nan)
    alpha = 1.0 / length
    started = False
    for i in range(len(v)):
        if not started:
            if i >= length - 1:
                window = v[i - length + 1: i + 1]
                if not np.isnan(window).any():
                    out[i] = window.mean()
                    started = True
        else:
            out[i] = out[i - 1] if np.isnan(v[i]) else alpha * v[i] + (1 - alpha) * out[i - 1]
    return pd.Series(out, index=s.index)


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return tr


def supertrend(df: pd.DataFrame, atr_len: int, factor: float) -> tuple[pd.Series, pd.Series]:
    """Port of TradingView ta.supertrend. direction: -1 = up (green), 1 = down (red)."""
    atr = rma(true_range(df), atr_len).to_numpy()
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
    close = df["close"].to_numpy()
    n = len(df)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    st = np.full(n, np.nan)
    direction = np.full(n, np.nan)

    for i in range(n):
        if np.isnan(atr[i]):
            continue
        up_b = hl2[i] + factor * atr[i]
        lo_b = hl2[i] - factor * atr[i]
        if i > 0 and not np.isnan(lower[i - 1]):
            lo_b = lo_b if (lo_b > lower[i - 1] or close[i - 1] < lower[i - 1]) else lower[i - 1]
            up_b = up_b if (up_b < upper[i - 1] or close[i - 1] > upper[i - 1]) else upper[i - 1]
        lower[i], upper[i] = lo_b, up_b

        if i == 0 or np.isnan(atr[i - 1]):
            d = 1
        elif st[i - 1] == upper[i - 1]:
            d = -1 if close[i] > up_b else 1
        else:
            d = 1 if close[i] < lo_b else -1
        direction[i] = d
        st[i] = lo_b if d == -1 else up_b

    return pd.Series(st, index=df.index), pd.Series(direction, index=df.index)


def adx(df: pd.DataFrame, length: int) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = rma(true_range(df), length)
    plus_di = 100 * rma(pd.Series(plus_dm, index=df.index), length) / tr
    minus_di = 100 * rma(pd.Series(minus_dm, index=df.index), length) / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return rma(dx.fillna(0), length)


def htf_supertrend(df: pd.DataFrame, cfg: Config) -> tuple[pd.Series, pd.Series]:
    """Higher-TF Supertrend mapped to chart bars using only CLOSED higher-TF candles."""
    kw = {"label": "left", "closed": "left"}
    if cfg.htf_offset:
        kw["offset"] = cfg.htf_offset
    htf = df.resample(cfg.htf, **kw).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    st, d = supertrend(htf, cfg.htf_atr_len, cfg.htf_factor)
    # shift(1): an HTF bar labelled at its start carries the PREVIOUS (closed) HTF value
    st_prev, d_prev = st.shift(1), d.shift(1)
    return (st_prev.reindex(df.index, method="ffill"),
            d_prev.reindex(df.index, method="ffill"))


# ───────────────────────── Signals ─────────────────────────
def build_signals(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    out = df.copy()
    out["st"], out["dir"] = supertrend(df, cfg.atr_len, cfg.factor)
    out["htf_st"], out["htf_dir"] = htf_supertrend(df, cfg)

    up = out["dir"] < 0
    htf_up = out["htf_dir"] < 0
    htf_valid = out["htf_dir"].notna() & out["htf_dir"].shift(1).notna()
    flip_up = up & ~up.shift(1, fill_value=True)
    flip_dn = ~up & up.shift(1, fill_value=False) & out["dir"].notna()
    htf_flip_up = htf_valid & htf_up & ~htf_up.shift(1, fill_value=True)
    htf_flip_dn = htf_valid & ~htf_up & htf_up.shift(1, fill_value=False)

    ok = htf_valid & out["dir"].notna()
    if cfg.use_adx:
        out["adx"] = adx(df, cfg.adx_len)
        ok &= out["adx"] >= cfg.adx_thr
    if cfg.start_date:
        ok &= out.index >= pd.Timestamp(cfg.start_date, tz=out.index.tz)
    if cfg.end_date:
        ok &= out.index <= pd.Timestamp(cfg.end_date, tz=out.index.tz)
    if cfg.use_session:
        t = out.index.time
        s = pd.to_datetime(cfg.session_start).time()
        e = pd.to_datetime(cfg.session_end).time()
        ok &= pd.Series([(s <= x < e) for x in t], index=out.index)
    ok &= pd.Series(out.index.dayofweek, index=out.index).isin(cfg.trade_days)

    out["long_sig"] = ok & htf_up & up & (flip_up | (cfg.trade_htf_flip & htf_flip_up))
    out["short_sig"] = ok & ~htf_up & ~up & (flip_dn | (cfg.trade_htf_flip & htf_flip_dn))
    if cfg.trade_dir == "long":
        out["short_sig"] = False
    elif cfg.trade_dir == "short":
        out["long_sig"] = False
    return out


# ───────────────────────── Backtest ─────────────────────────
def _floor_step(x: float, step: float) -> float:
    return math.floor(x / step) * step if x > 0 else 0.0


def backtest(df: pd.DataFrame, cfg: Config) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    d = build_signals(df, cfg)
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    st = d["st"].to_numpy(float)
    long_sig, short_sig = d["long_sig"].to_numpy(), d["short_sig"].to_numpy()
    idx = d.index

    cash = cfg.initial_capital
    net_profit = 0.0
    trades: list[dict] = []
    equity = np.full(len(d), np.nan)

    pos = 0            # +1 long, -1 short, 0 flat
    qty = 0.0
    qty_open = 0.0     # remaining qty
    entry_px = 0.0
    entry_time = None
    stop = tp = tp1 = np.nan
    tp1_done = False
    pending = None     # (side, tp, tp1, risk) to execute at next open
    realised = 0.0     # PnL of current trade so far (partials)

    def fee(px: float, q: float) -> float:
        return abs(px * q * cfg.point_value) * cfg.commission_pct / 100

    def close_part(px: float, q: float, reason: str, t) -> None:
        nonlocal cash, net_profit, qty_open, realised, pos
        px = px - cfg.slippage * pos  # slippage against you
        pnl = (px - entry_px) * q * pos * cfg.point_value - fee(px, q)
        cash += pnl
        net_profit += pnl
        realised += pnl
        qty_open -= q
        if qty_open <= 1e-12:
            trades.append({"entry_time": entry_time, "exit_time": t,
                           "side": "long" if pos > 0 else "short",
                           "qty": qty, "entry": entry_px, "exit": px,
                           "pnl": realised, "exit_reason": reason})
            pos = 0

    for i in range(len(d)):
        # 1) execute pending entry at this bar's open
        if pending is not None:
            side, p_tp, p_tp1, risk = pending
            pending = None
            if pos != 0 and pos != side:          # reverse if still in opposite trade
                close_part(o[i], qty_open, "reverse", idx[i])
            if pos == 0:
                px = o[i] + cfg.slippage * side
                if cfg.use_risk:
                    cap = cfg.initial_capital + net_profit if cfg.use_compound else cfg.initial_capital
                    q = _floor_step(cap * cfg.risk_pct / 100 / (risk * cfg.point_value), cfg.qty_step)
                else:
                    q = _floor_step(cash * cfg.default_pct_equity / 100 / (px * cfg.point_value), cfg.qty_step)
                if q > 0:
                    pos, qty, qty_open = side, q, q
                    entry_px, entry_time = px, idx[i]
                    tp, tp1, tp1_done, realised = p_tp, p_tp1, False, 0.0
                    cash -= fee(px, q)
                    net_profit -= fee(px, q)
                    realised -= fee(px, q)

        # 2) manage open position with levels set on the previous bar
        if pos != 0 and not np.isnan(stop):
            events = []  # (price, kind)
            if pos > 0:
                if o[i] <= stop:
                    events.append((o[i], "stop"))
                else:
                    if not np.isnan(stop) and l[i] <= stop:
                        events.append((stop, "stop"))
                    if cfg.use_partial and not tp1_done and h[i] >= tp1:
                        events.append((max(tp1, o[i]), "tp1"))
                    if cfg.use_tp and h[i] >= tp:
                        events.append((max(tp, o[i]), "tp"))
                    high_first = abs(o[i] - h[i]) < abs(o[i] - l[i])
                    # O->H->L->C : targets (higher prices) first; else stop first
                    events.sort(key=lambda e: -e[0] if high_first else e[0])
            else:
                if o[i] >= stop:
                    events.append((o[i], "stop"))
                else:
                    if h[i] >= stop:
                        events.append((stop, "stop"))
                    if cfg.use_partial and not tp1_done and l[i] <= tp1:
                        events.append((min(tp1, o[i]), "tp1"))
                    if cfg.use_tp and l[i] <= tp:
                        events.append((min(tp, o[i]), "tp"))
                    high_first = abs(o[i] - h[i]) < abs(o[i] - l[i])
                    # O->H->L->C : stop (higher price) first; else targets first
                    events.sort(key=lambda e: -e[0] if high_first else e[0])

            for px, kind in events:
                if pos == 0:
                    break
                if kind == "tp1":
                    part = _floor_step(qty * cfg.partial_pct / 100, cfg.qty_step)
                    part = min(part, qty_open)
                    tp1_done = True
                    if 0 < part < qty_open:
                        close_part(px, part, "tp1", idx[i])
                        continue
                close_part(px, qty_open, kind, idx[i])

        # 3) on bar close: update trailing stop and queue new signals
        if long_sig[i]:
            risk = c[i] - st[i]
            pending = (1, c[i] + cfg.rr * risk, c[i] + cfg.partial_rr * risk, risk)
        elif short_sig[i]:
            risk = st[i] - c[i]
            pending = (-1, c[i] - cfg.rr * risk, c[i] - cfg.partial_rr * risk, risk)
        stop = st[i]  # trailing stop for the next bar (Supertrend line)

        mtm = (c[i] - entry_px) * qty_open * pos * cfg.point_value if pos != 0 else 0.0
        equity[i] = cash + mtm

    # close anything still open at the last close
    if pos != 0:
        close_part(c[-1], qty_open, "end_of_data", idx[-1])
        equity[-1] = cash

    return pd.DataFrame(trades), pd.Series(equity, index=idx, name="equity"), d


def summarize(trades: pd.DataFrame, equity: pd.Series, cfg: Config) -> dict:
    if trades.empty:
        return {"trades": 0}
    wins = trades[trades.pnl > 0]
    losses = trades[trades.pnl <= 0]
    dd = equity / equity.cummax() - 1
    return {
        "trades": len(trades),
        "net_profit": round(trades.pnl.sum(), 2),
        "return_pct": round(100 * trades.pnl.sum() / cfg.initial_capital, 2),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2),
        "profit_factor": round(wins.pnl.sum() / abs(losses.pnl.sum()), 2) if len(losses) and losses.pnl.sum() != 0 else float("inf"),
        "avg_trade": round(trades.pnl.mean(), 2),
        "max_drawdown_pct": round(100 * dd.min(), 2),
        "longs": int((trades.side == "long").sum()),
        "shorts": int((trades.side == "short").sum()),
    }


# ───────────────────────── Data loading ─────────────────────────
def load_csv(path: str, tz: str | None = None) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [col.strip().lower() for col in df.columns]
    time_col = next(col for col in ("datetime", "date", "time", "timestamp") if col in df.columns)
    df[time_col] = pd.to_datetime(df[time_col])
    df = df.set_index(time_col).sort_index()
    if tz:
        df.index = df.index.tz_localize(tz) if df.index.tz is None else df.index.tz_convert(tz)
    return df[["open", "high", "low", "close"]].astype(float)


def load_yf(symbol: str, interval: str, period: str, tz: str | None = None) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(symbol, interval=interval, period=period, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [col.lower() for col in df.columns]
    if tz:
        df.index = df.index.tz_convert(tz)
    return df[["open", "high", "low", "close"]].dropna().astype(float)


# ───────────────────────── CLI ─────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(description="MTF Supertrend backtester")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="CSV with datetime,open,high,low,close")
    src.add_argument("--yf", help="Yahoo Finance symbol, e.g. ^NSEI, RELIANCE.NS, BTC-USD")
    p.add_argument("--interval", default="15m")
    p.add_argument("--period", default="60d")
    p.add_argument("--tz", default=None, help="e.g. Asia/Kolkata")
    p.add_argument("--htf", default="1h")
    p.add_argument("--htf-offset", default=None)
    p.add_argument("--atr", type=int, default=10)
    p.add_argument("--factor", type=float, default=3.0)
    p.add_argument("--htf-atr", type=int, default=10)
    p.add_argument("--htf-factor", type=float, default=3.0)
    p.add_argument("--dir", default="both", choices=["long", "short", "both"])
    p.add_argument("--htf-flip", action="store_true")
    p.add_argument("--adx", type=float, default=None, help="enable ADX filter with this threshold")
    p.add_argument("--rr", type=float, default=None, help="enable R:R take profit")
    p.add_argument("--partial", type=float, nargs=2, metavar=("RR", "PCT"), default=None)
    p.add_argument("--risk", type=float, default=None, help="risk %% per trade")
    p.add_argument("--compound", action="store_true")
    p.add_argument("--capital", type=float, default=100_000)
    p.add_argument("--qty-step", type=float, default=1.0)
    p.add_argument("--commission", type=float, default=0.03)
    p.add_argument("--slippage", type=float, default=0.0)
    p.add_argument("--session", nargs=2, metavar=("START", "END"), default=None)
    p.add_argument("--all-days", action="store_true", help="trade Sat/Sun too (crypto)")
    p.add_argument("--out", default="trades.csv")
    a = p.parse_args()

    cfg = Config(
        atr_len=a.atr, factor=a.factor, htf=a.htf, htf_offset=a.htf_offset,
        htf_atr_len=a.htf_atr, htf_factor=a.htf_factor, trade_dir=a.dir,
        trade_htf_flip=a.htf_flip, initial_capital=a.capital, qty_step=a.qty_step,
        commission_pct=a.commission, slippage=a.slippage, use_compound=a.compound,
    )
    if a.adx is not None:
        cfg.use_adx, cfg.adx_thr = True, a.adx
    if a.rr is not None:
        cfg.use_tp, cfg.rr = True, a.rr
    if a.partial is not None:
        cfg.use_partial, cfg.partial_rr, cfg.partial_pct = True, a.partial[0], a.partial[1]
    if a.risk is not None:
        cfg.use_risk, cfg.risk_pct = True, a.risk
    if a.session:
        cfg.use_session, cfg.session_start, cfg.session_end = True, a.session[0], a.session[1]
    if a.all_days:
        cfg.trade_days = set(range(7))

    df = load_csv(a.csv, a.tz) if a.csv else load_yf(a.yf, a.interval, a.period, a.tz)
    trades, equity, _ = backtest(df, cfg)

    for k, v in summarize(trades, equity, cfg).items():
        print(f"{k:>18}: {v}")
    if not trades.empty:
        trades.to_csv(a.out, index=False)
        print(f"\nTrades saved to {a.out}")


if __name__ == "__main__":
    main()
