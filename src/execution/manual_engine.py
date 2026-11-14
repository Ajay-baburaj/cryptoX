"""Manual paper orders, several open at once. Public quotes only; no broker order API or credentials."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
from uuid import uuid4

import aiohttp

UTC = timezone.utc
FEE = 0.0005
SLIPPAGE = 0.0002
IDENTITY = dict(strategy_id='manual_paper', strategy_name='Manual paper trading',
                symbol='BTCUSDT', venue='Paper · Binance public feed', currency='USDT')


def number(value, name, optional=False):
    if optional and (value is None or value == ''):
        return None
    if isinstance(value, bool):
        raise ValueError(f'{name} must be a positive number')
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValueError(f'{name} must be a positive number') from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be a positive number')
    return value


@dataclass
class ManualEngine:
    state_path: Path = field(default_factory=lambda: Path('data/paper/manual_state.json'))
    start_balance: float = 10000.
    balance: float = 10000.
    positions: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    mark_price: float | None = None
    last_update: str | None = None
    status: str = 'starting'
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self):
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text())
            if state.get('version') == 1:
                state['positions'] = [state['position']] if state['position'] else []
            elif state.get('version') != 2:
                raise ValueError('Unknown manual paper state version')
            for key in ('start_balance', 'balance', 'positions', 'trades', 'started_at'):
                setattr(self, key, state[key])

    def save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {k: getattr(self, k) for k in ('start_balance', 'balance', 'positions', 'trades', 'started_at')}
        tmp = self.state_path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'version': 2, **state}, allow_nan=False))
        os.replace(tmp, self.state_path)

    def fresh_price(self):
        if (self.status != 'ok' or self.mark_price is None or self.last_update is None
                or not 0 <= (datetime.now(UTC) - datetime.fromisoformat(self.last_update)).total_seconds() <= 15):
            raise ValueError('Live price unavailable or stale. Wait for the feed to reconnect.')
        return self.mark_price

    def find(self, position_id):
        for p in self.positions:
            if p['id'] == position_id:
                return p
        raise ValueError('Position changed or closed. Refresh the manual account.')

    def levels(self, data, reference, side):
        stop = number(data.get('stop'), 'Stop-loss', True)
        target = number(data.get('target'), 'Take-profit', True)
        trail = number(data.get('trail_pct'), 'Trailing distance', True)
        if trail is not None and trail >= 100:
            raise ValueError('Trailing distance must be below 100%')
        direction = 1 if side == 'long' else -1
        if stop is not None and direction * (reference - stop) <= 0:
            raise ValueError('Stop-loss must be below the price for a long, above for a short')
        if target is not None and direction * (target - reference) <= 0:
            raise ValueError('Take-profit must be above the price for a long, below for a short')
        return stop, target, trail

    def open(self, data):
        side = data.get('side')
        if side not in ('long', 'short'):
            raise ValueError('Side must be long or short')
        quote = self.fresh_price()
        direction = 1 if side == 'long' else -1
        entry = quote * (1 + direction * SLIPPAGE)
        quantity = number(data.get('quantity'), 'BTC quantity')
        stop, target, trail = self.levels(data, quote, side)
        notional = quantity * entry
        fee = notional * FEE
        in_use = sum(p['notional'] for p in self.positions)
        if not math.isfinite(notional) or in_use + notional + fee > self.balance:
            raise ValueError('Insufficient paper balance (1× total notional plus entry fee required)')
        position = {**IDENTITY, 'id': uuid4().hex, 'side': side, 'entry': entry,
                    'reference_entry': quote, 'entry_time': datetime.now(UTC).isoformat(),
                    'quantity': quantity, 'notional': notional, 'entry_fee': fee,
                    'stop': stop, 'target': target, 'trail_pct': trail,
                    'trail_anchor': quote, 'trailing_stop': None}
        self.positions.append(position)
        self.balance -= fee
        self._trail(position, quote)
        self.save()
        return position

    def _trail(self, p, quote):
        if p['trail_pct'] is None:
            return
        long = p['side'] == 'long'
        p['trail_anchor'] = (max if long else min)(quote, p['trail_anchor'])
        stop = p['trail_anchor'] * (1 + (-1 if long else 1) * p['trail_pct'] / 100)
        old = p['trailing_stop']
        p['trailing_stop'] = stop if old is None else (max if long else min)(stop, old)

    def update(self, position_id, data):
        p = self.find(position_id)
        quote = self.fresh_price()
        stop, target, trail = self.levels({**p, **data}, quote, p['side'])
        if trail != p['trail_pct']:
            p.update(trail_anchor=quote, trailing_stop=None)
        p.update(stop=stop, target=target, trail_pct=trail)
        self._trail(p, quote)
        self.save()

    def close(self, position_id, reason='manual_close'):
        p = self.find(position_id)
        quote = self.fresh_price()
        direction = 1 if p['side'] == 'long' else -1
        exit_price = quote * (1 - direction * SLIPPAGE)
        exit_fee = exit_price * p['quantity'] * FEE
        gross = direction * (exit_price - p['entry']) * p['quantity']
        pnl = gross - p['entry_fee'] - exit_fee
        self.balance += gross - exit_fee
        self.trades.append({**p, 'exit': exit_price, 'exit_time': datetime.now(UTC).isoformat(),
                            'exit_reason': reason, 'pnl': pnl, 'fees': p['entry_fee'] + exit_fee,
                            'ret_pct': pnl / p['notional'] * 100, 'balance_after': self.balance,
                            'data_quality': 'sampled_quotes'})
        self.positions.remove(p)
        self.save()

    def process_quote(self, quote, now=None):
        quote = number(quote, 'Quote')
        self.mark_price = quote
        self.last_update = (now or datetime.now(UTC)).isoformat()
        self.status = 'ok'
        for p in list(self.positions):
            direction = 1 if p['side'] == 'long' else -1
            # Existing stops are checked before advancing the trailing anchor.
            stops = [(p['stop'], 'stop_loss'), (p['trailing_stop'], 'trailing_stop')]
            stops = [(s, reason) for s, reason in stops if s is not None]
            if stops:
                stop, reason = max(stops, key=lambda pair: direction * pair[0])
                if direction * (quote - stop) <= 0:
                    self.close(p['id'], reason)
                    continue
            if p['target'] is not None and direction * (quote - p['target']) >= 0:
                self.close(p['id'], 'take_profit')
                continue
            self._trail(p, quote)
        if self.positions:
            self.save()

    async def refresh(self, session):
        async with session.get('https://data-api.binance.vision/api/v3/ticker/24hr',
                               params={'symbol': 'BTCUSDT'}) as response:
            response.raise_for_status()
            ticker = await response.json()
        now = datetime.now(UTC)
        age = now.timestamp() - float(ticker['closeTime']) / 1000
        if not -5 <= age <= 15:
            raise ValueError('Stale public quote')
        self.process_quote(ticker['lastPrice'], now)

    async def run(self):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            while True:
                try:
                    async with self._lock:
                        await self.refresh(session)
                except Exception:
                    self.status = 'degraded'
                    logging.getLogger(__name__).exception('manual paper quote refresh failed')
                await asyncio.sleep(2)

    def snapshot(self):
        positions, unrealized = [], 0.
        for position in self.positions:
            p = dict(position)
            if self.mark_price:
                direction = 1 if p['side'] == 'long' else -1
                exit_price = self.mark_price * (1 - direction * SLIPPAGE)
                value = direction * (exit_price - p['entry']) * p['quantity'] - exit_price * p['quantity'] * FEE
                unrealized += value
                net = value - p['entry_fee']
                p.update(mark_price=self.mark_price, unrealized_pnl=net, unrealized_pct=net / p['notional'] * 100)
            positions.append(p)
        equity = self.balance + unrealized
        wins = sum(t['pnl'] > 0 for t in self.trades)
        return {**IDENTITY, 'status': self.status, 'last_update': self.last_update,
                'started_at': self.started_at, 'mark_price': self.mark_price,
                'account': {'start_balance': self.start_balance, 'balance': self.balance, 'equity': equity,
                            'available': max(0., self.balance - sum(p['notional'] for p in positions)),
                            'pnl': equity - self.start_balance},
                'positions': positions, 'trades': list(reversed(self.trades)),
                'stats': {'trades': len(self.trades), 'wins': wins,
                          'losses': sum(t['pnl'] < 0 for t in self.trades),
                          'win_rate': wins / len(self.trades) * 100 if self.trades else None},
                'validation': 'Manual simulation · independent 10,000 USDT account',
                'rules': 'Market orders; multiple manual positions at once; 1× maximum total notional. Optional SL, TP and percentage trail per position, from best observed price. Fee 0.05% and slippage 0.02% per side. Checks every 2 seconds while the backend runs; gaps fill at the next observed quote. No funding or liquidation model.'}
