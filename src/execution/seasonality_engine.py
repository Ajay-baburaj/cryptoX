"""Forward-only Delta BTCUSD 21:00–23:00 UTC paper strategy.

Costs reproduce the supplied model: slipped-price return minus two fixed fee+GST
fractions of starting notional. Funding is not modeled. No exchange orders.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import os
from pathlib import Path
from collections.abc import Callable
import aiohttp

UTC=timezone.utc
STRATEGY_ID='delta_seasonality_21_23'
STRATEGY_NAME='BTCUSD session long · 21–23 UTC'
REST='https://api.india.delta.exchange'
FEE=.0005
GST=.18
SLIPPAGE=.0001
FEE_SIDE=FEE*(1+GST)
ENTRY_GRACE=90

def utc(value):
    result=datetime.fromisoformat(value) if isinstance(value,str) else value
    if result.tzinfo is None:raise ValueError('Timestamp must have a timezone')
    return result.astimezone(UTC)

def returns(entry,exit):
    effective_entry=entry*(1+SLIPPAGE);effective_exit=exit*(1-SLIPPAGE)
    return {'entry':effective_entry,'exit':effective_exit,'gross_return':exit/entry-1,
            'net_return':effective_exit/effective_entry-1-2*FEE_SIDE}

@dataclass
class SeasonalityEngine:
    state_path:Path=field(default_factory=lambda:Path('data/paper/seasonality_state.json'))
    poll_seconds:int=15
    on_event:Callable[[dict],None]|None=None
    start_balance:float=10000.
    balance:float=10000.
    started_at:str|None=None
    position:dict|None=None
    trades:list=field(default_factory=list)
    events:list=field(default_factory=list)
    last_session:str|None=None
    mark_price:float|None=None
    last_update:str|None=None
    status:str='starting'

    def __post_init__(self):
        if self.state_path.exists():
            state=json.loads(self.state_path.read_text())
            if state.get('version')!=1:raise ValueError('Unknown seasonality state version')
            for key in ('start_balance','balance','started_at','position','trades','events','last_session'):
                setattr(self,key,state[key])

    def save(self):
        self.state_path.parent.mkdir(parents=True,exist_ok=True)
        data={k:getattr(self,k) for k in ('start_balance','balance','started_at','position','trades','events','last_session')}
        data['version']=1
        tmp=self.state_path.with_suffix('.tmp');tmp.write_text(json.dumps(data,allow_nan=False));os.replace(tmp,self.state_path)

    def event(self,kind,now,**values):
        e={'type':kind,'time':now.isoformat(),'strategy_id':STRATEGY_ID,'strategy_name':STRATEGY_NAME,'symbol':'BTCUSD','side':'long',**values}
        self.events.append(e);self.events=self.events[-100:]
        return e

    def process(self,now,candles,quote):
        """Candles map UTC open timestamps to positive opens; quote must be fresh.

        Never open a past session on startup/recovery. If an existing position's exit
        was missed, close at the current observed quote, not a fabricated past fill.
        """
        now=utc(now)
        if not math.isfinite(quote) or quote<=0:raise ValueError('Invalid quote')
        candles={utc(t):float(v) for t,v in candles.items() if utc(t)<=now and math.isfinite(float(v)) and float(v)>0}
        if self.started_at is None:self.started_at=now.isoformat()
        self.mark_price=quote;self.last_update=now.isoformat();self.status='ok'
        emitted=[]
        if self.position:
            p=self.position;end=utc(p['scheduled_exit']);begin=utc(p['entry_time'])
            seen=set(p['observed_candles'])
            seen.update(t.isoformat() for t in candles if begin<=t<=end and (t-begin).total_seconds()%900==0)
            p['observed_candles']=sorted(seen)
            if now>=end:
                on_time=(now-end).total_seconds()<=ENTRY_GRACE and end in candles
                raw_exit=candles[end] if on_time else quote
                exit_at=end if on_time else now
                calc=returns(p['reference_entry'],raw_exit)
                pnl=p['notional']*calc['net_return']
                complete=all((begin+timedelta(minutes=15*i)).isoformat() in seen for i in range(9))
                t={**p,**calc,'reference_exit':raw_exit,'exit_time':exit_at.isoformat(),'observed_exit_time':now.isoformat(),
                   'exit_reason':'session_end' if on_time else 'delayed_exit','pnl':pnl,'fees':p['notional']*2*FEE_SIDE,
                   'ret_pct':calc['net_return']*100,'hold_hours':(exit_at-begin).total_seconds()/3600,
                   'session_complete':complete,'data_quality':'complete' if complete else 'missing_session_candles'}
                self.balance+=pnl;t['balance_after']=self.balance
                self.trades.append(t);self.position=None
                emitted.append(self.event('exit',now,price=calc['exit'],pnl=pnl,reason=t['exit_reason']))
        begin=now.replace(hour=21,minute=0,second=0,microsecond=0);key=begin.date().isoformat()
        if self.position is None and now>=begin and self.last_session!=key:
            if utc(self.started_at)>begin or (now-begin).total_seconds()>ENTRY_GRACE:
                self.last_session=key
                emitted.append(self.event('skipped',now,reason='entry_window_missed'))
            elif begin in candles:
                raw=candles[begin]
                self.position={'strategy_id':STRATEGY_ID,'strategy_name':STRATEGY_NAME,'symbol':'BTCUSD','venue':'Delta Exchange India','currency':'USD',
                    'side':'long','entry_time':begin.isoformat(),'observed_entry_time':now.isoformat(),
                    'scheduled_exit':(begin+timedelta(hours=2)).isoformat(),'reference_entry':raw,'entry':raw*(1+SLIPPAGE),
                    'notional':self.balance,'entry_fee':self.balance*FEE_SIDE,'stop':None,'observed_candles':[begin.isoformat()]}
                self.last_session=key
                emitted.append(self.event('entry',now,price=self.position['entry'],stop=None))
        self.save()  # Persist before notification hooks so retry/restart cannot duplicate trades.
        for e in emitted:
            if self.on_event:
                try:self.on_event(e)
                except Exception:logging.getLogger(__name__).exception('seasonality notification hook failed')
        return emitted

    async def tick(self,session):
        now=datetime.now(UTC)
        begin=utc(self.position['entry_time']) if self.position else now.replace(hour=21,minute=0,second=0,microsecond=0)
        end=min(now,begin+timedelta(hours=2,minutes=15))
        candles={}
        if end>=begin:
            async with session.get(REST+'/v2/history/candles',params={'symbol':'BTCUSD','resolution':'15m','start':int(begin.timestamp()),'end':int(end.timestamp())}) as r:
                r.raise_for_status();body=await r.json()
            if not body.get('success'):raise ValueError('Delta candles unavailable')
            for x in body['result']:
                t=datetime.fromtimestamp(x['time'],UTC)
                if t in candles:raise ValueError('Duplicate Delta candle')
                candles[t]=float(x['open'])
        async with session.get(REST+'/v2/tickers/BTCUSD') as r:
            r.raise_for_status();body=await r.json()
        if not body.get('success'):raise ValueError('Delta ticker unavailable')
        ticker=body['result'];observed=datetime.now(UTC)
        stamp=datetime.fromtimestamp(float(ticker['timestamp'])/1_000_000,UTC)
        if not -5<=(observed-stamp).total_seconds()<=90:raise ValueError('Stale Delta quote')
        self.process(observed,candles,float(ticker['close']))

    async def run(self):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            while True:
                try:await self.tick(session)
                except Exception:
                    self.status='degraded';logging.getLogger(__name__).exception('seasonality tick failed')
                await asyncio.sleep(self.poll_seconds)

    def snapshot(self):
        position=dict(self.position) if self.position else None
        unrealized=0.
        if position and self.mark_price:
            unrealized=position['notional']*returns(position['reference_entry'],self.mark_price)['net_return']
            position.update(mark_price=self.mark_price,unrealized_pnl=unrealized)
        wins=sum(t['pnl']>0 for t in self.trades)
        return {'strategy_id':STRATEGY_ID,'strategy_name':STRATEGY_NAME,'symbol':'BTCUSD','venue':'Delta Exchange India','currency':'USD',
                'status':self.status,'started_at':self.started_at,'last_update':self.last_update,'mark_price':self.mark_price,
                'account':{'start_balance':self.start_balance,'balance':self.balance,'equity':self.balance+unrealized,'pnl':self.balance+unrealized-self.start_balance},
                'position':position,'trades':list(reversed(self.trades)),'events':list(reversed(self.events)),
                'stats':{'trades':len(self.trades),'wins':wins,'losses':sum(t['pnl']<0 for t in self.trades),'win_rate':wins/len(self.trades)*100 if self.trades else None},
                'validation':'Unvalidated hypothesis · forward paper test',
                'rules':'Long at 21:00 UTC; exit 23:00 UTC (02:30–04:30 IST next day). 1× paper notional; no stop-loss. Fee 0.05% + 18% GST on fee, slippage 0.01% each side; funding excluded. Entry must be observed within 90 seconds; missed exits use the next fresh quote. Missing session candles are flagged, never erased.'}
