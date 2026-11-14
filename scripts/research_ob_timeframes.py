"""Run the preregistered Binance BTCUSDT perpetual OB timeframe comparison.

Protocol: research/ob_timeframe_protocol.md. Outputs: data/reports/ob_timeframes/.
"""
from __future__ import annotations
import argparse
from bisect import bisect_left
from dataclasses import replace
from itertools import product
import json
from pathlib import Path
import time
import numpy as np
import pandas as pd
from research.ob_timeframes import (Market,Rules,complete_bars,detect_zones,first_retest_entries,simulate,metrics,week_bootstrap,trade_at)

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data/binance_ob_timeframes'
OUT=ROOT/'data/reports/ob_timeframes'
PERIODS={'development':('2024-01-01','2025-01-01'),'validation':('2025-01-01','2026-01-01'),'test':('2026-01-01','2026-11-01')}
TFS={15:'15m',60:'1h',240:'4h'}

def ts(x):return pd.Timestamp(x,tz='UTC')
def identifier(tf,style,mitigation,buffer,exit):return f'{TFS[tf]}_{style}_{mitigation}_b{buffer}_{exit}'

def load_market():
    minutes=pd.read_parquet(DATA/'minutes.parquet')
    archives=pd.read_parquet(DATA/'funding.parquet')
    api=pd.read_json(DATA/'funding_api.json')
    assert np.array_equal(archives.calc_time.to_numpy(),api.fundingTime.to_numpy())
    assert np.allclose(archives.last_funding_rate,api.fundingRate.astype(float),atol=1e-12)
    assert (api.markPrice.astype(float)>0).all()
    fund=pd.DataFrame({'time':pd.to_datetime(api.fundingTime,unit='ms',utc=True),'rate':api.fundingRate.astype(float),'mark_price':api.markPrice.astype(float)})
    market=Market(minutes,fund)
    assert np.count_nonzero(market.funding_points)>3000,'Funding not aligned with candles'
    return market


def grid(m):
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'entries').mkdir(exist_ok=True);(OUT/'trades').mkdir(exist_ok=True)
    rows=[];counts=[];clock=time.monotonic()
    for tf,mitigation in product(TFS,('wick','close')):
        bars=complete_bars(m.minutes,tf)
        zones,visible=detect_zones(bars,mitigation)
        for style in ('touch','rejection'):
            e=first_retest_entries(m,bars,zones,visible,style)
            name=f'{TFS[tf]}_{style}_{mitigation}'
            e.to_parquet(OUT/'entries'/f'{name}.parquet',index=False)
            counts.append(dict(tf=TFS[tf],entry=style,mitigation=mitigation,source_bars=len(bars),zones=len(zones),candidates=len(e)))
            for buffer,exit in product((.25,.5),('0.5R','1R','2R','trail')):
                key=identifier(tf,style,mitigation,buffer,exit)
                rules=Rules(buffer=buffer,exit=exit)
                for period,(start,end) in PERIODS.items():
                    trades,s,_=simulate(m,e,rules,ts(start),ts(end))
                    rows.append(dict(id=key,tf=TFS[tf],entry=style,mitigation=mitigation,buffer=buffer,exit=exit,period=period,**s))
            print(f'GRID {name}: {len(zones)} zones, {len(e)} entries, {time.monotonic()-clock:.1f}s',flush=True)
    result=pd.DataFrame(rows);result.to_csv(OUT/'all_variants.csv',index=False)
    pd.DataFrame(counts).to_csv(OUT/'counts.csv',index=False)
    # Selection explicitly excludes all test rows.
    train=result[result.period=='development'].set_index('id')
    valid=result[result.period=='validation'].set_index('id')
    eligible=(train.n>=40)&(valid.n>=20)&(train.mean_R>0)&(valid.mean_R>0)
    ranking=pd.DataFrame({'dev_n':train.n,'val_n':valid.n,'dev_R':train.mean_R,'val_R':valid.mean_R,'passes':eligible})
    ranking['score']=np.minimum(ranking.dev_R,ranking.val_R)
    ranking['tf']=train.tf
    ranking.to_csv(OUT/'selection_train_validation.csv',index_label='id')
    chosen={}
    for label in TFS.values():
        ok=ranking[(ranking.tf==label)&ranking.passes]
        chosen[label]=None if ok.empty else ok.sort_values(['score','dev_n'],ascending=False).index[0]
    (OUT/'selected.json').write_text(json.dumps(chosen,indent=2))
    print('Train/validation-selected candidates:',chosen,flush=True)
    return result,chosen


def config_for(row):return Rules(buffer=float(row['buffer']),exit=row['exit'])
def entries_for(row):return pd.read_parquet(OUT/'entries'/f"{row['tf']}_{row['entry']}_{row['mitigation']}.parquet")


def detailed(m,result,chosen):
    baseline=[identifier(tf,'touch','wick',.25,'1R') for tf in TFS]
    keys=list(dict.fromkeys(baseline+[key for key in chosen.values() if key]))
    summary=[];monthly=[];sides=[];costs=[];daily_curves={}
    for key in keys:
        meta=result[result.id==key].iloc[0]
        e=entries_for(meta);rules=config_for(meta)
        alltrades=[];daily=[];scale=1.
        for period,(start,end) in PERIODS.items():
            trades,s,curve=simulate(m,e,rules,ts(start),ts(end),with_curve=True)
            trades['period']=period;alltrades.append(trades)
            lo,hi=week_bootstrap(trades,ts(start),ts(end))
            summary.append(dict(id=key,tf=meta.tf,kind='baseline' if key in baseline else 'selected',period=period,ci_low_R=lo,ci_high_R=hi,**s))
            dc=curve.resample('D').last()*scale
            if len(curve):scale*=float(curve.iloc[-1])
            daily.append(dc)
            for side,label in ((1,'long'),(-1,'short')):
                part=trades[trades.side==side] if not trades.empty else trades
                sides.append(dict(id=key,period=period,side=label,**metrics(part)))
            if not trades.empty:
                for month,part in trades.groupby(trades.entry_time.dt.strftime('%Y-%m')):
                    monthly.append(dict(id=key,period=period,month=month,**metrics(part)))
        pd.concat(alltrades,ignore_index=True).to_csv(OUT/'trades'/f'{key}.csv',index=False)
        daily_curves[key]=pd.concat(daily)
        for scenario,fee,slip,fund in [('gross',0.,0.,False),('fees_funding',.0005,0.,True),('base',.0005,.0002,True),('stress',.0005,.0005,True),('low_fee_assumption',.0002,.0002,True)]:
            t,s,_=simulate(m,e,replace(rules,fee=fee,slippage=slip,funding=fund),ts('2026-01-01'),ts('2026-11-01'))
            costs.append(dict(id=key,scenario=scenario,**s))
        print('DETAIL',key,flush=True)
    pd.DataFrame(summary).to_csv(OUT/'summary.csv',index=False)
    pd.DataFrame(monthly).to_csv(OUT/'monthly.csv',index=False)
    pd.DataFrame(sides).to_csv(OUT/'sides.csv',index=False)
    pd.DataFrame(costs).to_csv(OUT/'cost_sensitivity.csv',index=False)
    daily=pd.DataFrame(daily_curves);daily.to_csv(OUT/'daily_equity.csv',index_label='date')
    # Paired calendar-week bootstrap of average daily equity return differences.
    test=daily[daily.index>=ts('2026-01-01')]
    prior=daily[daily.index<ts('2026-01-01')].iloc[-1]
    returns=test.pct_change();returns.iloc[0]=test.iloc[0]/prior-1
    week=returns.index.tz_localize(None).to_period('W-SUN').astype(str)
    rng=np.random.default_rng(2917);paired=[]
    for a,b in ((baseline[0],baseline[1]),(baseline[0],baseline[2]),(baseline[1],baseline[2])):
        diff=returns[a]-returns[b]
        sums=diff.groupby(week).agg(['sum','count'])
        ix=rng.integers(len(sums),size=(4000,len(sums)))
        means=sums['sum'].to_numpy()[ix].sum(axis=1)/sums['count'].to_numpy()[ix].sum(axis=1)
        lo,hi=np.quantile(means,[.025,.975])*10000
        paired.append(dict(a=a,b=b,mean_daily_difference_bps=diff.mean()*10000,ci_low_bps=lo,ci_high_bps=hi))
    pd.DataFrame(paired).to_csv(OUT/'pairwise_bootstrap.csv',index=False)
    return pd.DataFrame(summary)


def null_portfolios(m,actual,rules,start,end,draws=250,seed=442):
    """Exact-count random schedules, matching month, side, 4h clock bucket and risk.

    Random trades are placed without overlaps by rejection sampling. Failed schedules are
    reported, never silently substituted with fewer trades. This is a conditional random-entry
    diagnostic, not a correction for the entire strategy search.
    """
    rng=np.random.default_rng(seed);cutoff=m.start(end);start_i=m.start(start)
    allidx=np.arange(start_i,cutoff)
    month=m.index[start_i:cutoff].strftime('%Y-%m').to_numpy();bucket=(m.index[start_i:cutoff].hour//4).to_numpy()
    pools={(mo,int(b)):allidx[(month==mo)&(bucket==b)] for mo in np.unique(month) for b in range(6)}
    templates=actual[['entry_time','side','risk_frac','atr','entry']].copy()
    rows=templates.to_dict('records');out=[];failed=0
    for draw in range(draws):
        occupied_starts=[];occupied_ends=[];trades=[];bad=False
        for k in rng.permutation(len(rows)):
            row=rows[k];when=pd.Timestamp(row['entry_time']);pool=pools[(when.strftime('%Y-%m'),when.hour//4)]
            success=False
            for attempt in range(1500):
                i=int(rng.choice(pool));pos=bisect_left(occupied_starts,i)
                if pos>0 and occupied_ends[pos-1]>=i:continue
                atr=row['atr']/row['entry']*m.open[i]
                t=trade_at(m,i,int(row['side']),0.,atr,rules,cutoff,stop_fraction=row['risk_frac'])
                if t is None:continue
                if pos<len(occupied_starts) and t['exit_i']>=occupied_starts[pos]:continue
                occupied_starts.insert(pos,i);occupied_ends.insert(pos,t['exit_i']);trades.append(t);success=True;break
            if not success:bad=True;break
        if bad:failed+=1;continue
        frame=pd.DataFrame(trades).sort_values('entry_i')
        out.append(dict(draw=draw,**metrics(frame)))
        if (draw+1)%50==0:print('NULL',draw+1,'/',draws,'n',len(actual),'failed',failed,flush=True)
    return pd.DataFrame(out),failed


def nulls(m,result,chosen,draws):
    baseline=[identifier(tf,'touch','wick',.25,'1R') for tf in TFS]
    keys=list(dict.fromkeys(baseline+[key for key in chosen.values() if key]))
    summaries=[]
    for key in keys:
        meta=result[result.id==key].iloc[0];rules=config_for(meta)
        actual=pd.read_csv(OUT/'trades'/f'{key}.csv',parse_dates=['entry_time'])
        actual=actual[actual.period=='test']
        if actual.empty:continue
        distribution,failed=null_portfolios(m,actual,rules,ts('2026-01-01'),ts('2026-11-01'),draws=draws)
        distribution.to_csv(OUT/f'null_{key}.csv',index=False)
        if distribution.empty:raise RuntimeError(f'No complete null portfolios: {key}')
        observed=float(actual.r_net.mean())
        p=(1+int((distribution.mean_R>=observed).sum()))/(1+len(distribution))
        summaries.append(dict(id=key,kind='baseline' if key in baseline else 'selected',n=len(actual),observed_R=observed,random_mean_R=distribution.mean_R.mean(),random_95pct_R=distribution.mean_R.quantile(.95),p=p,complete_draws=len(distribution),failed_draws=failed))
    table=pd.DataFrame(summaries)
    for kind,group in table.groupby('kind'):
        ordered=group.sort_values('p');adjusted=np.maximum.accumulate(ordered.p.to_numpy()*np.arange(len(ordered),0,-1))
        table.loc[ordered.index,'holm_p']=np.minimum(1,adjusted)
    table.to_csv(OUT/'null_summary.csv',index=False)
    print(table.to_string(index=False),flush=True)


def plots():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    s=pd.read_csv(OUT/'summary.csv');base=s[(s.kind=='baseline')&(s.period=='test')].set_index('tf').loc[list(TFS.values())]
    daily=pd.read_csv(OUT/'daily_equity.csv',index_col='date',parse_dates=True)
    fig,axes=plt.subplots(2,2,figsize=(13,8));colors=['#4285f4','#fbbc04','#34a853']
    labels=list(TFS.values())
    axes[0,0].bar(labels,base.return_pct,color=colors);axes[0,0].axhline(0,color='#666',lw=.7)
    axes[0,0].set(title='2026 test: net portfolio return',ylabel='Return (%)')
    axes[0,1].errorbar(labels,base.mean_R,yerr=[base.mean_R-base.ci_low_R,base.ci_high_R-base.mean_R],fmt='o',capsize=6,color='#444')
    axes[0,1].axhline(0,color='#a33',lw=1,ls='--');axes[0,1].set(title='2026 test: expectancy, 95% week-bootstrap CI',ylabel='Net R / trade')
    for tf,c in zip(TFS,colors):
        key=identifier(tf,'touch','wick',.25,'1R');curve=daily[key]
        axes[1,0].plot(curve.index,(curve-1)*100,label=TFS[tf],color=c)
        te=curve[curve.index>=ts('2026-01-01')];previous=curve[curve.index<ts('2026-01-01')].iloc[-1]
        axes[1,1].plot(te.index,(te/previous-1)*100,label=TFS[tf],color=c)
    axes[1,0].set(title='Development + validation + test equity',ylabel='Cumulative return (%)')
    axes[1,0].axvline(ts('2026-01-01'),ls='--',color='#777');axes[1,0].legend()
    axes[1,1].set(title='2026 test equity (reset to 1 January)',ylabel='Return (%)');axes[1,1].legend()
    for ax in axes[1,:]:ax.tick_params(axis='x',rotation=25)
    fig.suptitle('BTCUSDT perpetual: first OB retest, 1R target, same rules across timeframes\n0.5% equity risk; 0.05% fee + 0.02% slippage each side; historical funding',fontsize=12)
    fig.tight_layout(rect=(0,0,1,.93));fig.savefig(OUT/'baseline_comparison.png',dpi=180);fig.savefig(OUT/'baseline_comparison.pdf');plt.close(fig)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['grid','detail','null','plot','all'],default='all');parser.add_argument('--null-draws',type=int,default=250);args=parser.parse_args()
    if args.stage=='plot':plots();return
    m=load_market()
    if args.stage in ('grid','all'):result,chosen=grid(m)
    else:result=pd.read_csv(OUT/'all_variants.csv');chosen=json.loads((OUT/'selected.json').read_text())
    if args.stage in ('detail','all'):print(detailed(m,result,chosen).to_string(index=False),flush=True)
    if args.stage in ('null','all'):nulls(m,result,chosen,args.null_draws)
    if args.stage=='all':plots()

if __name__=='__main__':main()
