import numpy as np
import pandas as pd
from research.ob_timeframes import (Market,Rules,Zone,complete_bars,detect_zones,first_retest_entries,trade_at,walk,simulate)


def minutes(n=60):
    return pd.DataFrame({'open':110.,'high':111.,'low':109.,'close':110.,'volume':1.},index=pd.date_range('2024-01-01',periods=n,freq='min',tz='UTC'))


def test_only_full_closed_source_bars_are_used():
    raw=minutes(29).drop(pd.Timestamp('2024-01-01 00:02',tz='UTC'))
    assert complete_bars(raw,15).empty
    full=complete_bars(minutes(30),15)
    assert full.index[0]==pd.Timestamp('2024-01-01 00:15',tz='UTC')
    assert len(full)==2


def entry_fixture():
    raw=minutes(60)
    raw.iloc[10,raw.columns.get_loc('low')]=98. # before creation: never executable
    raw.iloc[20,raw.columns.get_loc('low')]=99.
    market=Market(raw);bars=complete_bars(raw,15);bars['atr']=[1.,100.,100.,100.]
    zone=Zone(0,bars.index[0],100.,95.,1,0,0)
    return market,bars,[zone],[(0,)]*len(bars)


def test_first_touch_fills_next_minute_with_previously_closed_atr():
    market,bars,zones,visible=entry_fixture()
    entries=first_retest_entries(market,bars,zones,visible,'touch')
    assert len(entries)==1
    assert entries.iloc[0].entry_i==21
    assert entries.iloc[0].atr==1.
    assert entries.iloc[0].touch_time>=zones[0].created


def test_rejection_waits_for_common_15m_bar_close():
    market,bars,zones,visible=entry_fixture()
    entries=first_retest_entries(market,bars,zones,visible,'rejection')
    assert len(entries)==1 and entries.iloc[0].entry_i==30


def test_invisible_first_touch_is_not_retried_when_zone_reappears():
    market,bars,zones,visible=entry_fixture()
    visible[0]=()
    assert first_retest_entries(market,bars,zones,visible,'touch').empty


def test_zone_born_around_price_is_not_a_fresh_retest():
    market,bars,zones,visible=entry_fixture()
    raw=market.minutes.copy()
    raw.iloc[14,raw.columns.get_loc('close')]=99.
    raw.iloc[15,raw.columns.get_loc('low')]=99.
    market=Market(raw)
    assert first_retest_entries(market,bars,zones,visible,'touch').empty


def test_no_signal_uses_future_pivot_bars():
    rng=np.random.default_rng(4);n=1000
    close=100+np.cumsum(rng.normal(0,.5,n));open_=np.r_[close[0],close[:-1]]
    bars=pd.DataFrame({'open':open_,'high':np.maximum(open_,close)+.2,'low':np.minimum(open_,close)-.2,'close':close,'segment':0},index=pd.date_range('2024-01-01',periods=n,freq='15min',tz='UTC'))
    all_z,all_v=detect_zones(bars)
    for stop in (200,400,700):
        prefix,pv=detect_zones(bars.iloc[:stop])
        assert [(z.created,z.top,z.bottom,z.side) for z in prefix]==[(z.created,z.top,z.bottom,z.side) for z in all_z if z.created<=bars.index[stop-1]]
        assert pv==all_v[:stop]


def test_stop_wins_same_minute_tie_and_gap_stop_uses_worse_open():
    raw=minutes(3);raw.loc[:,'open']=100.;raw.loc[:,'close']=100.;raw.loc[:,'high']=103.;raw.loc[:,'low']=97.
    m=Market(raw);rules=Rules(fee=0,slippage=0)
    assert walk(m,0,1,100.,98.,1.,rules,3)==(0,98.,'stop')
    raw.iloc[0,raw.columns.get_loc('open')]=96.
    assert walk(Market(raw),0,1,100.,98.,1.,rules,3)==(0,96.,'stop')


def test_trailing_ratchet_applies_from_next_minute():
    raw=minutes(2);raw['open']=[100.,104.];raw['close']=[104.,103.];raw['high']=[104.,105.];raw['low']=[99.,102.]
    assert walk(Market(raw),0,1,100.,98.,1.,Rules(exit='trail'),2)==(1,103.,'trail_stop')


def test_funding_debit_credit_and_fee_on_both_actual_notionals():
    raw=minutes(4);raw[['open','close']]=100.;raw['high']=100.1;raw['low']=99.9
    funding=pd.DataFrame({'time':[raw.index[0],raw.index[1]],'rate':[.0001,.0002],'mark_price':[100.,101.]})
    m=Market(raw,funding);rules=Rules(fee=.0005,slippage=0)
    long=trade_at(m,0,1,95.,1.,rules,4);short=trade_at(m,0,-1,105.,1.,rules,4)
    assert abs(long['funding']-.000202)<1e-12
    assert abs(short['funding']+.000202)<1e-12
    assert abs(long['ret_net']-(-.001-.000202))<1e-12
    assert abs(short['ret_net']-(-.001+.000202))<1e-12


def test_positions_do_not_cross_gaps_or_split_boundaries():
    raw=minutes(10).drop(minutes(10).index[4:6]);raw[['open','close']]=100.;raw['high']=100.1;raw['low']=99.9
    m=Market(raw);rules=Rules(fee=0,slippage=0)
    assert walk(m,0,1,100.,95.,1.,rules,len(raw))==(3,100.,'data_gap')
    assert walk(m,0,1,100.,95.,1.,rules,2)==(1,100.,'split_end')


def test_minute_marked_equity_matches_closed_trade_equity_and_single_position():
    m,b,z,v=entry_fixture();e=first_retest_entries(m,b,z,v,'touch');e=pd.concat([e,e],ignore_index=True)
    t,s,c=simulate(m,e,Rules(),m.index[0],m.index[-1]+pd.Timedelta(minutes=1),with_curve=True)
    assert len(t)==1
    assert np.isclose(c.iloc[-1],1+s['return_pct']/100)
    assert s['mtm_dd_pct']<=0
