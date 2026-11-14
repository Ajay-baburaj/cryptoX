import json
import math

import pytest

from execution.manual_engine import ManualEngine, FEE, SLIPPAGE
from test_auth import run_app, login


def engine(tmp_path):
    e = ManualEngine(state_path=tmp_path / 'manual.json')
    e.process_quote(100.)
    return e


@pytest.mark.parametrize('side,direction', [('long', 1), ('short', -1)])
def test_market_fill_costs_balance_and_manual_close(tmp_path, side, direction):
    e = engine(tmp_path)
    p = e.open({'side': side, 'quantity': 2})
    entry = 100 * (1 + direction * SLIPPAGE)
    assert p['entry'] == entry
    assert e.balance == pytest.approx(10000 - 2 * entry * FEE)
    assert e.snapshot()['account']['available'] == pytest.approx(e.balance - 2 * entry)
    e.process_quote(100 + direction * 10)
    e.close(p['id'])
    t = e.trades[0]
    expected = direction * (t['exit'] - entry) * 2 - t['fees']
    assert t['pnl'] == pytest.approx(expected)
    assert e.balance == pytest.approx(10000 + expected)
    assert e.snapshot()['account']['equity'] == e.balance
    assert e.positions == []
    assert t['exit_reason'] == 'manual_close'


@pytest.mark.parametrize('side,quote,reason', [
    ('long', 89, 'stop_loss'), ('long', 111, 'take_profit'),
    ('short', 111, 'stop_loss'), ('short', 89, 'take_profit')])
def test_stop_and_target_fill_at_observed_quote_including_gaps(tmp_path, side, quote, reason):
    e = engine(tmp_path)
    e.open({'side': side, 'quantity': 1, 'stop': 90 if side == 'long' else 110,
            'target': 110 if side == 'long' else 90})
    e.process_quote(quote)
    assert e.positions == []
    assert e.trades[0]['exit_reason'] == reason
    direction = 1 if side == 'long' else -1
    assert e.trades[0]['exit'] == quote * (1 - direction * SLIPPAGE)


@pytest.mark.parametrize('side,better,pullback,trigger,stop', [
    ('long', 120, 115, 107, 108), ('short', 80, 85, 89, 88)])
def test_trail_tightens_only_and_survives_restart(tmp_path, side, better, pullback, trigger, stop):
    e = engine(tmp_path)
    e.open({'side': side, 'quantity': 1, 'trail_pct': 10})
    e.process_quote(better)
    assert e.positions[0]['trailing_stop'] == pytest.approx(stop)
    e.process_quote(pullback)
    assert e.positions[0]['trailing_stop'] == pytest.approx(stop)
    restored = ManualEngine(state_path=e.state_path)
    assert restored.positions == e.positions
    assert restored.mark_price is None  # fresh quote required after restart
    restored.process_quote(trigger)
    assert restored.trades[0]['exit_reason'] == 'trailing_stop'
    assert ManualEngine(state_path=e.state_path).balance == restored.balance


def test_edit_and_disable_protection(tmp_path):
    e = engine(tmp_path)
    p = e.open({'side': 'long', 'quantity': 1, 'stop': 90, 'target': 130, 'trail_pct': 10})
    e.process_quote(110)
    e.update(p['id'], {'stop': 100, 'target': 140, 'trail_pct': 5})
    assert e.positions[0]['trailing_stop'] == pytest.approx(104.5)
    e.update(p['id'], {'stop': None, 'target': None, 'trail_pct': None})
    assert all(e.positions[0][k] is None for k in ('stop', 'target', 'trail_pct', 'trailing_stop'))
    e.process_quote(50)
    assert e.positions


@pytest.mark.parametrize('data', [
    {'quantity': 0}, {'quantity': -1}, {'quantity': math.nan}, {'quantity': math.inf},
    {'quantity': True}, {'quantity': 10000}, {'side': 'invalid'}, {'stop': 101},
    {'target': 99}, {'trail_pct': 100}, {'trail_pct': -1}, {'trail_pct': 'bad'},
])
def test_invalid_orders_do_not_mutate_balance(tmp_path, data):
    e = engine(tmp_path)
    with pytest.raises(ValueError):
        e.open({'side': 'long', 'quantity': 1, **data})
    assert e.balance == 10000
    assert e.positions == []


def test_multiple_positions_are_independent_and_share_the_notional_cap(tmp_path):
    e = engine(tmp_path)
    a = e.open({'side': 'long', 'quantity': 40, 'stop': 90})
    b = e.open({'side': 'long', 'quantity': 40, 'stop': 80})
    c = e.open({'side': 'short', 'quantity': 10})
    with pytest.raises(ValueError, match='Insufficient'):
        e.open({'side': 'long', 'quantity': 20})
    assert len(e.snapshot()['positions']) == 3
    e.process_quote(85)
    assert [t['id'] for t in e.trades] == [a['id']]
    assert [p['id'] for p in e.positions] == [b['id'], c['id']]
    e.close(c['id'])
    assert [p['id'] for p in ManualEngine(state_path=e.state_path).positions] == [b['id']]


def test_version_1_state_with_one_position_is_migrated(tmp_path):
    e = engine(tmp_path)
    p = e.open({'side': 'long', 'quantity': 1})
    e.state_path.write_text(json.dumps({'version': 1, 'start_balance': 10000., 'balance': e.balance,
                                        'position': p, 'trades': [], 'started_at': e.started_at}))
    assert ManualEngine(state_path=e.state_path).positions == [p]


def test_stale_prices_are_rejected(tmp_path):
    e = engine(tmp_path)
    e.last_update = '2020-01-01T00:00:00+00:00'
    with pytest.raises(ValueError, match='stale'):
        e.open({'side': 'long', 'quantity': 1})
    e.process_quote(100)
    p = e.open({'side': 'long', 'quantity': 1})
    e.status = 'degraded'
    with pytest.raises(ValueError, match='stale'):
        e.close(p['id'])
    assert not e.trades


def test_manual_api_auth_validation_positions_and_history(tmp_path):
    async def scenario(client, backend, app, cfg):
        e = engine(tmp_path)
        app['manual'] = e
        assert (await client.get('/api/manual')).status == 401
        assert (await client.post('/api/manual/open', json={'side': 'long', 'quantity': 1})).status == 401
        await login(client)
        assert (await client.post('/api/manual/open', data='side=long')).status == 415
        assert (await client.post('/api/manual/open', json=[])).status == 400
        assert (await client.post('/api/manual/open', data='{', headers={'Content-Type':'application/json'})).status == 400
        assert (await client.post('/api/manual/open', json={'side': 'long', 'quantity': -1})).status == 400
        opened = await client.post('/api/manual/open', json={'side': 'long', 'quantity': 1, 'stop': 90})
        assert opened.status == 200
        data = await opened.json()
        assert data['positions'][0]['strategy_id'] == 'manual_paper'
        position_id = data['positions'][0]['id']
        positions = await (await client.get('/api/positions')).json()
        assert positions['positions'][0]['strategy_id'] == 'manual_paper'
        assert (await client.post('/api/manual/close', json={'position_id': 'old-position'})).status == 400
        assert e.positions[0]['id'] == position_id
        assert (await client.post('/api/manual/update', json={'position_id': position_id, 'target': 120, 'trail_pct': 5})).status == 200
        assert (await client.post('/api/manual/close', json={'position_id': position_id})).status == 200
        trades = await (await client.get('/api/trades')).json()
        assert trades['trades'][0]['exit_reason'] == 'manual_close'
        assert trades['trades'][0]['strategy_id'] == 'manual_paper'
        assert (await client.post('/api/manual/close', json={})).status == 400
    run_app(tmp_path, scenario)
