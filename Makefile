.PHONY: setup data backtest strategy-backtest strategy-optimize daily-strategy-backtest ob-rejection-backtest ob-rejection-research ob-rejection-baseline ob-touch-backtest ob-touch-research mytradesetup-backtest ob15-diagnosis ob1h-backtest ob1h-grid ob15m-backtest ob15m-grid ob5m-backtest ob5m-grid firebase-check ema-vwap-backtest ema-vwap-research paper frontend test test-frontend volume-orderflow

setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -e '.[dev]'

data:
	.venv/bin/python scripts/download_history.py --symbol BTCUSD --interval 1m --start 2025-11-01

backtest:
	.venv/bin/python scripts/run_backtest.py

strategy-backtest:
	.venv/bin/python scripts/backtest_ema_rsi_engulfing.py

strategy-optimize:
	.venv/bin/python scripts/optimize_ema_rsi_engulfing.py

daily-strategy-backtest:
	.venv/bin/python scripts/backtest_daily_sma_ema_rsi_adx.py

ob-rejection-backtest:
	.venv/bin/python scripts/backtest_ob_rejection.py

ob-rejection-research:
	.venv/bin/python scripts/research_ob_rejection.py

ob-rejection-baseline:
	.venv/bin/python scripts/backtest_ob_rejection_baseline.py

ob-touch-backtest:
	.venv/bin/python scripts/backtest_ob_touch_15m.py

ob-touch-research:
	.venv/bin/python scripts/research_ob_touch_15m.py

ema-vwap-backtest:
	.venv/bin/python scripts/backtest_ema_vwap.py

ema-vwap-research:
	.venv/bin/python scripts/research_ema_vwap.py

paper:
	.venv/bin/python scripts/run_paper.py

frontend:
	.venv/bin/python -m http.server 8000 --directory frontend

test:
	.venv/bin/python -m pytest -q; status=$$?; if [ $$status -eq 5 ]; then echo "No tests collected (empty suite)"; else exit $$status; fi

test-frontend:
	node --test tests/test_smc.cjs

mytradesetup-backtest:
	.venv/bin/python scripts/backtest_mytradesetup.py

ob15-diagnosis:
	.venv/bin/python scripts/research_ob15_diagnosis.py all

ob1h-backtest:
	PYTHONPATH=src .venv/bin/python scripts/backtest_ob_mitigation_1h.py

ob1h-grid:
	PYTHONPATH=src .venv/bin/python scripts/backtest_ob_mitigation_1h.py --grid

ob15m-backtest:
	PYTHONPATH=src .venv/bin/python scripts/backtest_ob_mitigation_1h.py --tf 15

ob15m-grid:
	PYTHONPATH=src .venv/bin/python scripts/backtest_ob_mitigation_1h.py --tf 15 --grid --periods development,validation

ob5m-backtest:
	PYTHONPATH=src .venv/bin/python scripts/backtest_ob_mitigation_1h.py --tf 5

ob5m-grid:
	PYTHONPATH=src .venv/bin/python scripts/backtest_ob_mitigation_1h.py --tf 5 --grid --periods development,validation

firebase-check:
	PYTHONPATH=src .venv/bin/python scripts/firebase_check.py

seasonality-backtest:
	.venv/bin/python scripts/backtest_seasonality.py $(or $(INPUT),BTCUSD_15m.csv)

volume-orderflow:
	.venv/bin/python scripts/research_volume_orderflow.py
