"""Causal, equal-rule order-block timeframe research on 1m futures candles.

Internal structure adaptation of the supplied Smart Money Concepts Pine by © LuxAlgo.
CC BY-NC-SA 4.0, https://creativecommons.org/licenses/by-nc-sa/4.0/ . Non-commercial.
This is an independent research engine; no production strategy or orders are changed.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from strategy.luxalgo_internal_ob import wilder_rma

MINUTE = 60_000_000_000

@dataclass
class Zone:
    id: int
    created: pd.Timestamp
    top: float
    bottom: float
    side: int
    source_i: int
    origin_i: int
    expiry: pd.Timestamp | None = None
    warmed: bool = True


def complete_bars(minutes: pd.DataFrame, tf: int) -> pd.DataFrame:
    out = minutes.resample(f'{tf}min',closed='left',label='right',origin='start_day').agg(
        open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'),
        volume=('volume','sum'),count=('close','count'))
    out=out[out['count']==tf].copy()
    out['segment']=out.index.to_series().diff().gt(pd.Timedelta(minutes=tf)).cumsum().to_numpy()
    out['atr']=np.nan
    for _,run in out.groupby('segment'):
        prev=run['close'].shift()
        tr=pd.concat([run.high-run.low,(run.high-prev).abs(),(run.low-prev).abs()],axis=1).max(axis=1)
        out.loc[run.index,'atr']=wilder_rma(tr,14)
    return out


def detect_zones(bars: pd.DataFrame, mitigation: str='wick') -> tuple[list[Zone],list[tuple[int,...]]]:
    """Confirmed internal breaks and the newest five blocks after each source-bar close.

    Source keeps at most 100 live blocks and removes forward through the array. We preserve
    that order. Unusual inverted parsed candles are carried by the detector like Pine, then
    rejected as untradable by the entry generator.
    """
    zones=[]; visible=[()] * len(bars)
    offset=0
    for _,run in bars.groupby('segment',sort=False):
        H,L,C=(run[c].to_numpy(float) for c in ('high','low','close'))
        prev=run.close.shift()
        tr=pd.concat([run.high-run.low,(run.high-prev).abs(),(run.low-prev).abs()],axis=1).max(axis=1)
        atr200=wilder_rma(tr,200).to_numpy()
        volatile=H-L>=2*atr200
        ph=np.where(volatile,L,H); pl=np.where(volatile,H,L)
        def state(): return dict(leg=0,high=np.nan,low=np.nan,hi=0,lo=0,ch=False,cl=False)
        internal,swing=state(),state(); active=[]
        def update(s,i,size):
            if i<size:return
            p=i-size
            nh=H[p]>H[p+1:i+1].max(); nl=L[p]<L[p+1:i+1].min()
            leg=0 if nh else 1 if nl else s['leg']
            if leg==s['leg']:return
            s['leg']=leg
            if nh:s.update(high=H[p],hi=p,ch=False)
            else:s.update(low=L[p],lo=p,cl=False)
        for i,t in enumerate(run.index):
            prior_h,prior_l=internal['high'],internal['low']
            update(swing,i,50);update(internal,i,5)
            bull=(i>0 and np.isfinite(swing['high']) and C[i]>internal['high'] and C[i-1]<=prior_h
                  and not internal['ch'] and internal['high']!=swing['high'])
            bear=(i>0 and np.isfinite(swing['low']) and C[i]<internal['low'] and C[i-1]>=prior_l
                  and not internal['cl'] and internal['low']!=swing['low'])
            for side,fired in ((1,bull),(-1,bear)):
                if not fired:continue
                p=internal['hi' if side==1 else 'lo'];internal['ch' if side==1 else 'cl']=True
                if p>=i:continue
                pick=p+int(np.argmin(pl[p:i]) if side==1 else np.argmax(ph[p:i]))
                zone=Zone(len(zones),t,float(ph[pick]),float(pl[pick]),side,offset+i,offset+pick,warmed=i>=199)
                zones.append(zone);active.insert(0,zone)
                if len(active)>100:active.pop().expiry=t
            j=0
            while j<len(active):
                z=active[j]
                broken=(C[i] if mitigation=='close' else L[i])<z.bottom if z.side==1 else (C[i] if mitigation=='close' else H[i])>z.top
                if broken:z.expiry=t;active.pop(j)
                j+=1  # preserve the supplied Pine's forward removal semantics
            visible[offset+i]=tuple(z.id for z in active[:5])
        # Runs end at an actual missing source candle. No zones survive that outage.
        if offset+len(run)<len(bars):
            for z in active:
                z.expiry=run.index[-1]
        offset+=len(run)
    return zones,visible


class Market:
    def __init__(self,minutes:pd.DataFrame,funding:pd.DataFrame|None=None):
        self.minutes=minutes;self.index=minutes.index.as_unit('ns');self.ns=self.index.asi8
        self.open,self.high,self.low,self.close=(minutes[c].to_numpy(float) for c in ('open','high','low','close'))
        breaks=np.flatnonzero(np.diff(self.ns)!=MINUTE)
        ends=np.append(breaks,len(self.ns)-1)
        self.run_end=np.repeat(ends,np.diff(np.r_[-1,ends]))
        points=np.zeros(len(self.ns));self.funding_source='none'
        if funding is not None and len(funding):
            ftime=pd.to_datetime(funding['time'],utc=True).dt.floor('min').dt.as_unit('ns').astype('int64').to_numpy()
            idx=np.searchsorted(self.ns,ftime)
            valid=(idx<len(self.ns))
            valid &= self.ns[np.minimum(idx,len(self.ns)-1)]==ftime
            marks=funding['mark_price'].to_numpy(float)
            rates=funding['rate'].to_numpy(float)
            np.add.at(points,idx[valid],marks[valid]*rates[valid])
            self.funding_source='settlement mark price'
        self.funding_points=points;self.funding_cum=np.cumsum(points)

    def start(self,time):return int(np.searchsorted(self.ns,pd.Timestamp(time).as_unit('ns').value))


def first_retest_entries(market:Market,bars:pd.DataFrame,zones:list[Zone],visible:list[tuple[int,...]],entry_style:str) -> pd.DataFrame:
    """First revisit after confirmation. All feature values were known at that revisit."""
    rows=[];ns=market.ns;source_ns=bars.index.as_unit('ns').asi8;source_atr=bars.atr.to_numpy()
    confirms=complete_bars(market.minutes,15) if entry_style=='rejection' else None
    for z in zones:
        if not z.warmed or not z.top>z.bottom:continue
        start=market.start(z.created)
        end=market.start(z.expiry) if z.expiry is not None else len(ns)
        if start>=len(ns) or end<=start:continue
        end=min(end,int(market.run_end[start])+1)
        hit=(market.low[start:end]<=z.top) if z.side==1 else (market.high[start:end]>=z.bottom)
        if not hit.any():continue
        touch=start+int(np.argmax(hit))
        # A retest must approach from outside; a zone born around price is not a fresh revisit.
        if touch==0 or ns[touch]-ns[touch-1]!=MINUTE:continue
        if not (market.close[touch-1]>z.top if z.side==1 else market.close[touch-1]<z.bottom):continue
        known=int(np.searchsorted(source_ns,ns[touch],side='right'))-1
        if known<0 or z.id not in visible[known]:continue  # first touch consumed, even when invisible
        a=float(source_atr[known])
        if not np.isfinite(a) or a<=0:continue
        if entry_style=='touch':
            entry=touch+1
            signal_time=market.index[touch]+pd.Timedelta(minutes=1)
        else:
            signal_time=market.index[touch].floor('15min')+pd.Timedelta(minutes=15)
            if signal_time not in confirms.index:continue
            candle=confirms.loc[signal_time]
            if z.side==1:
                if not(candle['low']>=z.bottom and candle['close']>z.top):continue
            else:
                if not(candle['high']<=z.top and candle['close']<z.bottom):continue
            entry=market.start(signal_time)
        if entry>=len(ns) or ns[entry]!=signal_time.as_unit('ns').value or entry>market.run_end[touch]:continue
        if z.expiry is not None and market.index[entry]>=z.expiry:continue
        known_entry=int(np.searchsorted(source_ns,ns[entry],side='right'))-1
        if z.id not in visible[known_entry]:continue
        rows.append(dict(block_id=z.id,created=z.created,signal_time=signal_time,touch_time=market.index[touch],entry_time=market.index[entry],entry_i=entry,side=z.side,top=z.top,bottom=z.bottom,atr=a))
    columns=['block_id','created','signal_time','touch_time','entry_time','entry_i','side','top','bottom','atr']
    return pd.DataFrame(rows,columns=columns).sort_values(['entry_i','created','block_id'],ascending=[True,False,False]).reset_index(drop=True)


@dataclass(frozen=True)
class Rules:
    buffer:float=0.25
    exit:str='1R'
    fee:float=0.0005
    slippage:float=0.0002
    risk_fraction:float=0.005
    max_leverage:float=3.0
    max_hours:int=96
    min_risk:float=0.002
    funding:bool=True


def walk(m:Market,start:int,side:int,entry:float,stop:float,atr:float,rules:Rules,cutoff:int):
    end=min(m.start(m.index[start]+pd.Timedelta(hours=rules.max_hours)),int(m.run_end[start])+1,cutoff)
    risk=side*(entry-stop)
    if end<=start:raise ValueError('No execution bar')
    if rules.exit!='trail':
        rr=float(rules.exit.removesuffix('R'));target=entry+side*rr*risk
        hi,lo=m.high[start:end],m.low[start:end]
        sl=(lo<=stop) if side==1 else (hi>=stop)
        tp=(hi>=target) if side==1 else (lo<=target)
        si=int(np.argmax(sl)) if sl.any() else len(hi)
        ti=int(np.argmax(tp)) if tp.any() else len(hi)
        if si<len(hi) and si<=ti:
            i=start+si;fill=min(stop,m.open[i]) if side==1 else max(stop,m.open[i])
            return i,fill,'stop'
        if ti<len(hi):
            # No optimistic price improvement at take profit, modeled as triggered market exit.
            return start+ti,target,'target'
    else:
        active=False
        for i in range(start,end):
            if (m.low[i]<=stop) if side==1 else (m.high[i]>=stop):
                fill=min(stop,m.open[i]) if side==1 else max(stop,m.open[i])
                return i,fill,'trail_stop' if active else 'stop'
            favorable=m.high[i] if side==1 else m.low[i]
            if side*(favorable-entry)>=risk:active=True
            if active:
                candidate=favorable-side*atr
                stop=max(stop,candidate) if side==1 else min(stop,candidate)
    last=end-1
    full_time=ns_duration(m,start,end)>=rules.max_hours*60
    reason='time' if full_time else 'split_end' if end==cutoff else 'data_gap'
    return last,m.close[last],reason


def ns_duration(m,start,end):return (m.ns[end-1]-m.ns[start])//MINUTE+1


def trade_at(m:Market,start:int,side:int,ref_stop:float,atr:float,rules:Rules,cutoff:int,stop_fraction:float|None=None):
    entry=m.open[start]*(1+side*rules.slippage)
    stop=entry*(1-side*stop_fraction) if stop_fraction is not None else ref_stop
    risk=side*(entry-stop);frac=risk/entry
    if risk<=0 or frac<rules.min_risk:return None
    exit_i,ref_fill,reason=walk(m,start,side,entry,stop,atr,rules,cutoff)
    fill=ref_fill*(1-side*rules.slippage)
    gross=side*(ref_fill-m.open[start])/m.open[start]
    fees=rules.fee*(entry+fill)/entry
    funding_points=(m.funding_cum[exit_i]-m.funding_cum[start]) if rules.funding else 0.0
    fund=side*funding_points/entry
    net=side*(fill-entry)/entry-fees-fund
    leverage=min(rules.risk_fraction/frac,rules.max_leverage)
    return dict(entry_i=start,exit_i=exit_i,entry_time=m.index[start],exit_time=m.index[exit_i],side=side,entry=entry,exit=fill,stop=stop,atr=atr,risk_frac=frac,ret_gross=gross,ret_net=net,r_net=net/frac,fees=fees,funding=fund,slippage_cost=gross-(net+fees+fund),leverage=leverage,equity_ret=leverage*net,reason=reason)


def simulate(m:Market,entries:pd.DataFrame,rules:Rules,start:pd.Timestamp,end:pd.Timestamp,with_curve=False):
    start_i=m.start(start);cutoff=m.start(end)
    subset=entries[(entries.entry_i>=start_i)&(entries.entry_i<cutoff)]
    trades=[];busy=start_i-1;equity=1.0;peak=1.0;dd=0.0;cursor=start_i
    curve=np.ones(cutoff-start_i) if with_curve else None
    for r in subset.itertuples(index=False):
        i=int(r.entry_i)
        if i<=busy:continue
        stop=r.bottom-rules.buffer*r.atr if r.side==1 else r.top+rules.buffer*r.atr
        t=trade_at(m,i,int(r.side),float(stop),float(r.atr),rules,cutoff)
        if t is None:continue
        j=t['exit_i'];lev=t['leverage'];entry=t['entry']
        if curve is not None:curve[cursor-start_i:i-start_i]=equity
        funding=(m.funding_cum[i:j+1]-m.funding_cum[i])*t['side']/entry if rules.funding else 0
        marked=equity*(1+lev*(t['side']*(m.close[i:j+1]-entry)/entry-rules.fee-funding))
        new_equity=equity*(1+t['equity_ret']);marked[-1]=new_equity
        highs=np.maximum.accumulate(np.r_[peak,marked])[1:]
        dd=min(dd,float(np.min(marked/highs-1)));peak=max(peak,float(marked.max()))
        if curve is not None:curve[i-start_i:j+1-start_i]=marked
        t.update(block_id=r.block_id,created=r.created,touch_time=r.touch_time,equity_before=equity,equity_after=new_equity)
        trades.append(t);equity=new_equity;busy=j;cursor=j+1
    if curve is not None:curve[cursor-start_i:]=equity
    frame=pd.DataFrame(trades)
    summary=metrics(frame);summary.update(return_pct=(equity-1)*100,mtm_dd_pct=dd*100)
    series=pd.Series(curve,index=m.index[start_i:cutoff],name='equity') if curve is not None else None
    return frame,summary,series


def metrics(trades:pd.DataFrame):
    if trades.empty:return dict(n=0,win_pct=np.nan,mean_R=np.nan,PF=np.nan,sum_R=0.,avg_risk_pct=np.nan,avg_fee_R=np.nan,avg_funding_R=np.nan,avg_slippage_R=np.nan,mean_hold_h=np.nan,return_pct=0.)
    r=trades.r_net
    losses=-r[r<0].sum();wins=r[r>0].sum()
    return dict(n=len(trades),win_pct=float((r>0).mean()*100),mean_R=float(r.mean()),PF=float(wins/losses) if losses else np.inf,
                sum_R=float(r.sum()),avg_risk_pct=float(trades.risk_frac.mean()*100),avg_fee_R=float((trades.fees/trades.risk_frac).mean()),
                avg_funding_R=float((trades.funding/trades.risk_frac).mean()),avg_slippage_R=float((trades.slippage_cost/trades.risk_frac).mean()),
                mean_hold_h=float((trades.exit_time-trades.entry_time).dt.total_seconds().mean()/3600),
                return_pct=float(((1+trades.equity_ret).prod()-1)*100))


def week_bootstrap(trades:pd.DataFrame,start,end,draws=4000,seed=1957):
    """Calendar-week cluster bootstrap of per-trade mean net R, includes empty weeks."""
    if trades.empty:return np.nan,np.nan
    days=pd.date_range(start,end-pd.Timedelta(days=1),freq='D')
    weekkeys=days.tz_localize(None).to_period('W-SUN').astype(str).unique()
    frame=trades.copy();frame['week']=frame.entry_time.dt.tz_localize(None).dt.to_period('W-SUN').astype(str)
    sums=frame.groupby('week').r_net.agg(['sum','count']).reindex(weekkeys,fill_value=0)
    rng=np.random.default_rng(seed);ix=rng.integers(len(sums),size=(draws,len(sums)))
    denom=sums['count'].to_numpy()[ix].sum(axis=1);num=sums['sum'].to_numpy()[ix].sum(axis=1)
    samples=np.divide(num,denom,out=np.full(draws,np.nan),where=denom>0)
    return tuple(np.nanquantile(samples,[.025,.975]))
