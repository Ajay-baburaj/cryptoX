from unittest.mock import Mock

import pandas as pd
import pytest

from btc_agents.agents import decide
from btc_agents.context import add_context
from btc_agents.data import attach_trade_flow, download_delta, download_delta_funding, download_delta_open_interest
from btc_agents.features import complete_bars, features, validate_minutes
from btc_agents.news import connect, parse_feed, store
from btc_agents.replay import Candidate, Market, ReplayConfig, forecast_report, run, walk_forward


def utc(value):
    return pd.Timestamp(value, tz="UTC")


def minutes(start="2026-01-05", periods=360):
    index = pd.date_range(utc(start), periods=periods, freq="min")
    return pd.DataFrame(dict(open=100., high=101., low=99., close=100., volume=25.), index=index)


def candidate_row(**overrides):
    values = {"m5_close": 110, "m5_range_high": 109, "m5_range_low": 96, "m5_rvol": 1.5,
              "m5_atr": 1, "h1_atr": 5,
              "h1_zone_support_high": 90, "h1_zone_support_strength": 60,
              "h1_zone_resistance_low": 112, "h1_zone_resistance_strength": 60,
              "h1_momentum": .01, "m15_close": 108, "m15_ema20": 107, "m15_ema50": 106,
              "m15_atr": 2, "m15_rsi": 55, "h1_taker_imbalance": .1, "h4_bias": 1,
              "h4_adx": 25}
    return pd.Series(values | overrides, name=utc("2026-01-05 04:00"))


def test_higher_bar_is_visible_only_at_its_close_and_expires_after_a_gap():
    frame = minutes(periods=12 * 60)
    frame.loc[utc("2026-01-05 07:59"), ["close", "high"]] = 130
    excluded = frame.drop(utc("2026-01-05 09:45"))
    matrix = features(validate_minutes(excluded))
    assert matrix.loc[utc("2026-01-05 07:45"), "h4_close"] == 100
    assert matrix.loc[utc("2026-01-05 08:00"), "h4_close"] == 130
    assert pd.isna(matrix.loc[utc("2026-01-05 12:00"), "h4_close"])
    assert utc("2026-01-05 09:50") not in matrix.index
    assert utc("2026-01-05 09:55") in matrix.index
    prefix = features(validate_minutes(frame.loc[frame.index < utc("2026-01-05 07:45")]))
    pd.testing.assert_frame_equal(prefix, matrix.loc[prefix.index], check_freq=False)


def test_four_hour_boundary_and_duplicate_rejection():
    frame = minutes(periods=240)
    assert complete_bars(validate_minutes(frame), "4h").index.tolist() == [utc("2026-01-05 04:00")]
    with pytest.raises(ValueError, match="unique"):
        validate_minutes(pd.concat([frame, frame.iloc[[0]]]))


def test_optional_trade_flow_requires_a_matching_full_bar():
    base = minutes(periods=30)
    archive = base.assign(taker_buy_volume=10.)
    archive.loc[archive.index[15], "volume"] = 26.
    joined = validate_minutes(attach_trade_flow(base, archive))
    bars = complete_bars(joined, "15m")
    assert bars.taker_buy_volume.iloc[0] == 150
    assert pd.isna(bars.taker_buy_volume.iloc[1])


def test_regime_switches_score_weights_and_is_reported():
    trend = decide(candidate_row(h4_adx=25, h4_volatility="normal"))
    assert trend.regime == "TREND"
    high_vol = decide(candidate_row(h4_adx=25, h4_volatility="high"))
    assert high_vol.regime == "HIGH_VOL"
    assert high_vol.score != trend.score
    flat = decide(candidate_row(m5_close=90, m5_range_high=109, m5_range_low=96))
    assert flat.action == "FLAT" and flat.regime == "TREND"


def test_master_respects_four_hour_and_context_vetoes():
    qualified = decide(candidate_row())
    assert qualified.action == "LONG" and qualified.risk_multiplier == 1
    assert decide(candidate_row(h4_bias=-1)).action == "FLAT"
    assert decide(candidate_row(h4_adx=15)).reason == "4h_range"
    assert decide(candidate_row(event_blackout=True)).reason == "scheduled_macro_blackout"
    assert decide(candidate_row(ctx_funding_rate=.001, ctx_oi_change_1h=.04)).action == "FLAT"
    assert decide(candidate_row(news_security_count=1)).risk_multiplier == .5


def test_headlines_are_deduplicated_and_first_seen_controls_replay(tmp_path):
    xml = b"""<rss><channel><item><title>Bitcoin ETF approved</title>
    <link>https://example.org/story?utm_source=rss</link>
    <pubDate>Mon, 05 Jan 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
    path = tmp_path / "news.sqlite"
    db = connect(path)
    try:
        articles = list(parse_feed(xml))
        assert store(db, "coindesk", articles, utc("2026-01-05 10:11")) == 1
        assert store(db, "gdelt", [("Bitcoin rewrite", "https://www.example.org/story", None)],
                     utc("2026-01-05 10:20")) == 0
    finally:
        db.close()
    stamps = [utc("2026-01-05 10:00"), utc("2026-01-05 10:15")]
    out = add_context(pd.DataFrame(index=stamps), news_db=path)
    assert out.news_count.tolist() == [0, 1]


def test_macro_context_respects_availability_and_expires(tmp_path):
    context = tmp_path / "context.csv"
    context.write_text("available_at,metric,value,source\n2026-01-05T10:05:00Z,funding_rate,0.001,venue\n")
    calendar = tmp_path / "events.csv"
    calendar.write_text("event_at,available_at\n2026-01-05T10:30:00Z,2026-01-05T10:20:00Z\n")
    times = [utc("2026-01-05 10:00"), utc("2026-01-05 10:15"),
             utc("2026-01-05 10:30"), utc("2026-01-05 23:00")]
    out = add_context(pd.DataFrame(index=times), context, calendar)
    assert out.ctx_funding_rate.isna().tolist() == [True, False, False, True]
    assert out.event_blackout.tolist() == [False, False, True, False]


def test_replay_charges_funding_after_entry_and_stop_wins_an_ambiguous_minute():
    frame = minutes(periods=261)
    frame.loc[utc("2026-01-05 00:03"), ["high", "low"]] = [110, 95]
    funding = pd.Series([.001, .002, .003], index=pd.date_range(utc("2026-01-05 00:01"), periods=3, freq="min"))
    candidate = Candidate(frame.index[0], 1, atr=1, targets=(108,))
    trades = run(Market(frame, funding), [candidate], frame.index[0], frame.index[-1],
                 ReplayConfig(fee_bps=0, friction_bps=0))
    trade = trades.iloc[0]
    assert trade.entry_at == frame.index[1]
    assert trade.exit_reason == "stop"
    assert trade.funding_pnl == pytest.approx(-.005 * trade.notional)


def test_replay_keeps_outages_visible():
    frame = minutes(periods=270).drop(utc("2026-01-05 00:44"))
    candidate = Candidate(frame.index[0], -1, fixed_hold=True)
    trades = run(Market(frame), [candidate], frame.index[0], frame.index[-1], ReplayConfig())
    assert trades.status.tolist() == ["unresolved"]
    assert trades.exit_at.iloc[0] == utc("2026-01-05 00:43")


def test_forward_diagnostics_exclude_missing_minute_inside_the_horizon():
    frame = minutes(periods=550).drop(utc("2026-01-05 00:30"))
    early = Candidate(frame.index[0], 1)
    late = Candidate(utc("2026-01-05 01:00"), -1)
    result = forecast_report(Market(frame), {"test": [early, late]}, frame.index[0], frame.index[-1], 1)
    assert result.hours.tolist() == [1, 4]
    assert result.signals.tolist() == [1, 1]
    assert result.coverage_pct.tolist() == [50., 50.]


def test_delta_download_keeps_half_open_windows_and_merges_cache(tmp_path, monkeypatch):
    path = tmp_path / "candles.parquet"
    start = utc("2026-01-05")

    def candles(session, url, params):
        return {"result": [dict(time=when, open=100, high=101, low=99, close=100, volume=10)
                           for when in range(params["start"], params["end"] + 1, 60)]}

    mocked = Mock(side_effect=candles)
    monkeypatch.setattr("btc_agents.data.get_json", mocked)
    download_delta(start, start + pd.Timedelta(minutes=2), path)
    updated = download_delta(start + pd.Timedelta(minutes=1), start + pd.Timedelta(minutes=3), path)
    assert updated.index.tolist() == list(pd.date_range(start, periods=3, freq="min"))
    pd.testing.assert_frame_equal(pd.read_parquet(path), updated)
    assert mocked.call_count == 2


def test_walk_forward_emits_only_two_month_eval_windows():
    frame = minutes()
    rows = walk_forward(Market(frame), {"full": []}, utc("2025-01-01"), utc("2025-11-01"), ReplayConfig())
    assert rows.test_start.tolist() == [utc("2025-07-01"), utc("2025-09-01")]
    assert rows.test_end_exclusive.tolist() == [utc("2025-09-01"), utc("2025-11-01")]


def test_delta_funding_uses_settlement_boundaries_and_converts_percent(monkeypatch):
    start = utc("2026-01-05")
    times = pd.date_range(start, periods=24, freq="h")
    frame = pd.DataFrame({"time": times, "open": [.01] * 8 + [-.02] * 16})
    for field in ("high", "low", "close"):
        frame[field] = frame.open
    monkeypatch.setattr("btc_agents.data.delta_history", lambda *args: frame)
    funding = download_delta_funding(start, start + pd.Timedelta(days=1))
    assert funding.settled_at.tolist() == times[::8].tolist()
    assert funding.rate.tolist() == pytest.approx([.0001, -.0002, -.0002])
    frame.loc[3, ["open", "high", "low", "close"]] = .03
    with pytest.raises(ValueError, match="changes outside"):
        download_delta_funding(start, start + pd.Timedelta(days=1))


def test_delta_oi_changes_are_available_after_close_and_respect_gaps(monkeypatch):
    start = utc("2026-01-05")
    times = pd.date_range(start, periods=5, freq="h").delete(2)
    frame = pd.DataFrame({"time": times, "close": [100, 110, 150, 120]})
    monkeypatch.setattr("btc_agents.data.delta_history", lambda *args: frame)
    observations = download_delta_open_interest(start, start + pd.Timedelta(hours=6))
    assert observations.available_at.tolist() == [
        utc("2026-01-05 02:00:01"), utc("2026-01-05 05:00:01")]
    assert observations.value.tolist() == pytest.approx([.1, -.2])
