import numpy as np
import pytest

from research.volume_orderflow import Market, DAY, profile, value_area, sequential_holds, trade, window_levels


def market(n=10, o=100., funding=None):
    a = np.full(n, o)
    return Market(a.copy(), a + 1, a - 1, a.copy(), np.ones(n), np.full(n, .5), funding if funding is not None else np.zeros(n))


def test_profile_conserves_volume_and_spreads_uniformly():
    origin, hist = profile(np.array([100.]), np.array([103.5]), np.array([8.]), 1.)
    assert origin == 100 and hist.sum() == pytest.approx(8) and hist == pytest.approx([2, 2, 2, 2])


def test_value_area_expands_from_poc_to_reach_share():
    hist = np.array([1., 2, 10, 5, 1, 1])
    poc, val, vah = value_area(0., hist, 1., .7)
    assert (poc, val, vah) == (2.5, 2, 4)
    assert hist[2:4].sum() >= .7 * hist.sum()


def test_window_levels_never_use_later_minutes():
    m = market(DAY * 2)
    before = window_levels(m, 0)[0].copy()
    m.h[DAY:] += 500
    m.v[DAY:] *= 90
    assert window_levels(m, 0)[0] == pytest.approx(before)


@pytest.mark.parametrize('side,stop,target', [(1, 99.5, 100.5), (-1, 100.5, 99.5)])
def test_stop_wins_a_same_minute_tie(side, stop, target):
    m = market()
    exit_i, result = trade(m, 1, side, stop, target, 8)
    assert exit_i == 1 and result == pytest.approx(side * (stop / 100 - 1))


def test_gap_through_stop_fills_at_worse_open():
    m = market()
    m.o[3], m.h[3], m.l[3] = 90, 91, 89
    assert trade(m, 1, 1, 95, None, 8)[1] == pytest.approx(-.10)


def test_entry_beyond_levels_is_rejected():
    assert trade(market(), 1, 1, 101, None, 8) is None
    assert trade(market(), 1, 1, None, 99, 8) is None


@pytest.mark.parametrize('side,sign', [(1, -1), (-1, 1)])
def test_funding_charges_longs_and_pays_shorts_only_while_held(side, sign):
    funding = np.zeros(10)
    funding[[1, 4, 9]] = .001
    assert trade(market(funding=funding), 1, side, None, None, 6)[1] == pytest.approx(sign * .001)


def test_held_signals_do_not_overlap_and_enter_next_minute():
    trades = sequential_holds(market(), [(0, 1), (2, 1), (5, -1)], 3)
    assert [t[0] for t in trades] == [1, 6]
