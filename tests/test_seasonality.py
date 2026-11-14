from datetime import datetime,timedelta,timezone
import math
import pytest
from execution.seasonality_engine import SeasonalityEngine,returns,FEE_SIDE,SLIPPAGE,STRATEGY_ID

UTC=timezone.utc
BEGIN=datetime(2026,11,5,21,tzinfo=UTC)

def engine(tmp_path):
    e=SeasonalityEngine(state_path=tmp_path/'state.json')
    e.process(BEGIN-timedelta(minutes=1),{},100.)
    return e

def candles():return {BEGIN+timedelta(minutes=15*i):100.+i for i in range(9)}

def test_exact_supplied_fee_gst_slippage_arithmetic():
    r=returns(100.,110.)
    assert r['net_return']==110*(1-SLIPPAGE)/(100*(1+SLIPPAGE))-1-2*FEE_SIDE
    assert r['gross_return']==pytest.approx(.1)

def test_forward_entry_and_exact_exit_with_complete_session(tmp_path):
    e=engine(tmp_path);e.process(BEGIN+timedelta(seconds=15),candles(),100.)
    assert e.position['entry']==100.01
    assert len(e.position['observed_candles'])==1 # future bars are not observed
    e.process(BEGIN+timedelta(hours=2,seconds=15),candles(),108.)
    assert e.position is None and len(e.trades)==1
    t=e.trades[0]
    assert t['session_complete'] and t['strategy_id']==STRATEGY_ID
    assert t['fees']==pytest.approx(11.8)
    assert e.balance==pytest.approx(10000*(1+returns(100,108)['net_return']))

def test_never_enters_session_that_started_before_activation(tmp_path):
    e=SeasonalityEngine(state_path=tmp_path/'state.json')
    e.process(BEGIN+timedelta(seconds=10),candles(),100.)
    assert e.position is None and e.events[-1]['reason']=='entry_window_missed'

def test_missing_entry_candle_waits_then_skips(tmp_path):
    e=engine(tmp_path);e.process(BEGIN+timedelta(seconds=15),{},100.)
    assert e.position is None and e.last_session is None
    e.process(BEGIN+timedelta(seconds=100),candles(),100.)
    assert e.position is None and e.last_session==BEGIN.date().isoformat()

def test_incomplete_session_keeps_real_trade_and_flags_it(tmp_path):
    e=engine(tmp_path);e.process(BEGIN,{BEGIN:100.},100.)
    e.process(BEGIN+timedelta(hours=2),{BEGIN+timedelta(hours=2):95.},95.)
    assert len(e.trades)==1 and e.trades[0]['pnl']<0
    assert e.trades[0]['data_quality']=='missing_session_candles'

def test_missed_exit_uses_current_quote_not_past_open(tmp_path):
    e=engine(tmp_path);e.process(BEGIN,{BEGIN:100.},100.)
    e.process(BEGIN+timedelta(hours=3),candles(),90.)
    assert e.trades[0]['reference_exit']==90.
    assert e.trades[0]['exit_reason']=='delayed_exit'
    assert e.trades[0]['hold_hours']==3

def test_restart_preserves_open_position_and_never_duplicates(tmp_path):
    e=engine(tmp_path);e.process(BEGIN,candles(),100.)
    resumed=SeasonalityEngine(state_path=e.state_path)
    resumed.process(BEGIN+timedelta(hours=2),candles(),108.)
    resumed.process(BEGIN+timedelta(hours=2,minutes=1),candles(),108.)
    assert len(resumed.trades)==1
    again=SeasonalityEngine(state_path=e.state_path)
    assert again.balance==resumed.balance and again.position is None

def test_flat_price_loses_costs_and_mark_to_market_includes_exit_costs(tmp_path):
    e=engine(tmp_path);e.process(BEGIN,{BEGIN:100.},100.)
    p=e.snapshot()['position']
    assert p['unrealized_pnl']==pytest.approx(10000*returns(100,100)['net_return'])
    assert p['unrealized_pnl']<0

def test_invalid_quote_does_not_mutate_position(tmp_path):
    e=engine(tmp_path)
    for q in [0,-1,math.nan,math.inf]:
        with pytest.raises(ValueError):e.process(BEGIN,candles(),q)
    assert e.position is None

def test_notifications_include_strategy_and_no_stop_is_supported(tmp_path):
    from execution.push import compose
    e=engine(tmp_path);events=e.process(BEGIN,candles(),100.)
    msg=compose(events[0]);assert 'session long' in msg['title'] and 'no stop-loss' in msg['body']
