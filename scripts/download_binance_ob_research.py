"""Verified public Binance USD-M BTCUSDT candles/funding for the OB timeframe study."""
from __future__ import annotations
import asyncio
import hashlib
import io
import json
from pathlib import Path
import zipfile
import aiohttp
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/binance_ob_timeframes'
BASE = 'https://data.binance.vision/data/futures/um/monthly'

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / 'raw'; raw.mkdir(exist_ok=True)
    months = pd.date_range('2023-11-01', '2026-10-01', freq='MS').strftime('%Y-%m').tolist()
    sem = asyncio.Semaphore(4)
    manifest = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        async def fetch(kind, month):
            stem = f'BTCUSDT-1m-{month}' if kind == 'klines' else f'BTCUSDT-fundingRate-{month}'
            url = f'{BASE}/{kind}/BTCUSDT/' + ('1m/' if kind == 'klines' else '') + stem + '.zip'
            dest = raw / (stem + '.zip')
            async with sem:
                for attempt in range(3):
                    try:
                        async with session.get(url + '.CHECKSUM') as resp:
                            resp.raise_for_status(); checksum = (await resp.text()).split()[0]
                        blob = dest.read_bytes() if dest.exists() else None
                        if blob is None or hashlib.sha256(blob).hexdigest() != checksum:
                            async with session.get(url) as resp:
                                resp.raise_for_status(); blob = await resp.read()
                            assert hashlib.sha256(blob).hexdigest() == checksum, 'Checksum mismatch'
                            dest.write_bytes(blob)
                        with zipfile.ZipFile(io.BytesIO(blob)) as z:
                            files = [n for n in z.namelist() if n.endswith('.csv')]
                            assert len(files) == 1
                            payload = z.read(files[0])
                        frame = pd.read_csv(io.BytesIO(payload))
                        if kind == 'klines':
                            # Futures archives have a header; fail on unexpected schemas.
                            assert 'open_time' in frame and 'close' in frame, frame.columns.tolist()
                            frame = frame[['open_time', 'open', 'high', 'low', 'close', 'volume']]
                            time = pd.to_numeric(frame.pop('open_time'))
                            unit = 'us' if time.iloc[0] > 10**14 else 'ms'
                            frame.index = pd.to_datetime(time, unit=unit, utc=True)
                            frame.index.name = 'minute'
                            frame = frame.astype(float)
                            assert frame.index.strftime('%Y-%m').unique().tolist() == [month]
                        else:
                            assert 'calc_time' in frame and 'last_funding_rate' in frame, frame.columns.tolist()
                            frame['time'] = pd.to_datetime(frame['calc_time'], unit='ms', utc=True)
                        manifest.append({'kind':kind,'month':month,'url':url,'sha256':checksum,'bytes':len(blob),'rows':len(frame)})
                        print(kind, month, len(frame), 'SHA256 verified', flush=True)
                        return frame
                    except Exception:
                        if attempt == 2: raise
                        await asyncio.sleep(1 + attempt)
        candles, funding = [], []
        results = await asyncio.gather(*(fetch(kind, month) for kind in ('klines','fundingRate') for month in months))
        candles = pd.concat(results[:len(months)]).sort_index()
        funding = pd.concat(results[len(months):], ignore_index=True).sort_values('time')
        expected = pd.date_range(candles.index.min(), candles.index.max(), freq='min')
        missing = expected.difference(candles.index)
        repairs = []
        for day in missing.floor('D').unique():
            start = int(day.timestamp()*1000)
            params = {'symbol':'BTCUSDT','interval':'1m','startTime':start,'endTime':start+86400000-1,'limit':1500}
            dest = OUT / f'gap_{day.strftime("%Y%m%d")}_rest.json'
            if dest.exists():
                blob = dest.read_bytes(); body = json.loads(blob)
            else:
                async with session.get('https://fapi.binance.com/fapi/v1/klines', params=params) as resp:
                    resp.raise_for_status(); body = await resp.json()
                blob = json.dumps(body).encode(); dest.write_bytes(blob)
            if not body: continue
            frame = pd.DataFrame(body).iloc[:,:6]
            frame.columns = ['time','open','high','low','close','volume']
            frame.index = pd.to_datetime(frame.pop('time'),unit='ms',utc=True)
            frame.index.name = 'minute'; frame = frame.astype(float)
            frame = frame[frame.index.isin(missing)]
            candles = pd.concat([candles,frame]).sort_index()
            repairs.append({'date':str(day),'rows':len(frame),'source':'https://fapi.binance.com/fapi/v1/klines','params':params,'sha256':hashlib.sha256(blob).hexdigest()})
            print('REST gap repair:',day,len(frame),flush=True)
        assert not candles.index.has_duplicates
        assert not funding['time'].duplicated().any()
        assert (candles['high'] >= candles[['open','close','low']].max(axis=1)).all()
        assert (candles['low'] <= candles[['open','close','high']].min(axis=1)).all()
        assert (candles[['open','high','low','close']] > 0).all().all()
        assert (candles['volume'] >= 0).all()
        candles.to_parquet(OUT/'minutes.parquet', compression='zstd')
        funding.to_parquet(OUT/'funding.parquet', index=False, compression='zstd')
        (OUT/'manifest.json').write_text(json.dumps(sorted(manifest,key=lambda x:(x['kind'],x['month'])),indent=2))
        gaps = candles.index.to_series().diff()
        audit = {'rows':len(candles),'first':str(candles.index.min()),'last':str(candles.index.max()),'archive_missing_minutes':len(missing),'repairs':repairs,'missing_minutes':int((candles.index.max()-candles.index.min()).total_seconds()/60+1-len(candles)), 'gaps':{str(k):str(v) for k,v in gaps[gaps>pd.Timedelta(minutes=1)].items()},'funding_events':len(funding),'funding_max_gap_hours':funding['time'].diff().dt.total_seconds().max()/3600}
        (OUT/'audit.json').write_text(json.dumps(audit,indent=2))
        print(json.dumps(audit,indent=2),flush=True)
        # Funding history API includes settlement mark price; archive rates remain authoritative.
        try:
            start = int(candles.index[0].timestamp()*1000); end = int((candles.index[-1]+pd.Timedelta(minutes=1)).timestamp()*1000)-1
            records=[]
            while start<=end:
                async with session.get('https://fapi.binance.com/fapi/v1/fundingRate',params={'symbol':'BTCUSDT','startTime':start,'endTime':end,'limit':1000}) as resp:
                    resp.raise_for_status(); body=await resp.json()
                if not body: break
                records.extend(body); start=int(body[-1]['fundingTime'])+1
            api=pd.DataFrame(records)
            api.to_json(OUT/'funding_api.json',orient='records',indent=2)
            print('Funding API records:',len(api),flush=True)
        except Exception as exc:
            print('Funding mark-price API unavailable; use documented candle-price proxy:',repr(exc),flush=True)

if __name__=='__main__': asyncio.run(main())
