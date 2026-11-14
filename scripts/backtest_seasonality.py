"""Replay the user's complete-session CSV model; no network or trading orders."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from execution.seasonality_engine import returns,STRATEGY_ID,STRATEGY_NAME

def backtest(path):
    df=pd.read_csv(path)
    df['timestamp']=pd.to_datetime(df['timestamp'],utc=True)
    if df['timestamp'].duplicated().any():raise ValueError('Duplicate candle timestamps')
    df['open']=pd.to_numeric(df['open'])
    if not (np.isfinite(df.open)&(df.open>0)).all():raise ValueError('Invalid open prices')
    df=df.sort_values('timestamp').set_index('timestamp');rows=[];skipped=0
    for day,candles in df.groupby(df.index.date):
        begin=pd.Timestamp(day,tz='UTC')+pd.Timedelta(hours=21);end=begin+pd.Timedelta(hours=2)
        required=pd.date_range(begin,periods=9,freq='15min')
        if not required.isin(candles.index).all():skipped+=1;continue
        entry=float(candles.loc[begin,'open']);exit=float(candles.loc[end,'open'])
        calc=returns(entry,exit)
        rows.append({'strategy_id':STRATEGY_ID,'strategy_name':STRATEGY_NAME,'date':day,'entry_time':begin,'exit_time':end,
                     'entry':entry,'exit':exit,'gross_return':calc['gross_return'],'net_return':calc['net_return']})
    result=pd.DataFrame(rows)
    if not result.empty:result['equity']=10000*(1+result.net_return).cumprod()
    return result,skipped

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',type=Path,default=Path('data/reports/seasonality_backtest.csv'));a=p.parse_args()
    result,skipped=backtest(a.input)
    print('Trades:',len(result),'Incomplete days skipped:',skipped)
    if not result.empty:
        print('Win rate:',(result.net_return>0).mean()*100,'Net return:',(result.equity.iloc[-1]/10000-1)*100)
        a.output.parent.mkdir(parents=True,exist_ok=True);result.to_csv(a.output,index=False)
