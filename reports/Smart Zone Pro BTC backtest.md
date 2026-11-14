# Smart Zone Pro fails BTC's out-of-sample test

**No: under honest testing, this study could not build a profitable BTC strategy on Smart Zone Pro-style zones.** Three independent builds on three years of 1-minute BTC perpetual data covered zones and rejection signals on 5m to 4h, higher-timeframe zones with lower-timeframe triggers, and placebo-level controls. All three reach the same result: gross expectancy near zero and net expectancy negative after 0.14% round-trip costs. More than 5,600 rule variants produced no survivor of multiple-testing correction, and every rule selected on 2024-2025 lost or went flat in 2026 (best: -0.018R, 95% CI -0.34 to +0.33). The most damaging result is that real zones attract no more price reaction than arbitrary levels of the same width, and the star score mostly measures zone width. A positive 96-trade walk-forward and a few 4h cells leave a small effect unexcluded, but nothing here justifies live capital. One limit governs every number: the Pine source is protected, so these tests cover independent reconstructions from the published description and not the script itself. The verdict is firm for the reconstructions and strong, but unproven, for the actual indicator.

## Three separately built tests share one clean setup

The primary data is **1,578,240 gap-free Binance USD-M BTCUSDT perpetual 1m bars from November 2023 to October 2026, with historical funding** ([minutes.parquet](../data/binance_ob_timeframes/minutes.parquet)). It stands in for BTCUSD because the repo's Delta BTCUSD file covers only 2026 and is **missing about 22% of its span**, including holes of 30 and 29 days ([replicate.log](../research/smart_zone/same_tf/results/replicate.log)). Delta therefore serves only as a replication. Base costs are 0.05% taker plus 0.02% slippage per side plus funding, with scenarios for zero cost, maker entry and 18% GST ([mtf config](../research/smart_zone/mtf/config.py)). The Delta fee schedule itself could not be confirmed, because the support pages returned 404, so check it against the in-app rate card.

The two strategy backtests froze train 2024, validation 2025 and test January-October 2026 before computing outcomes, and physically cut the data at 2025-12-31 during selection ([run_dev.py](../research/smart_zone/mtf/run_dev.py); [protocol.py](../research/smart_zone/same_tf/protocol.py)). The placebo study used a separate development period through June 2025 and a holdout from July 2025 to October 2026 ([PROTOCOL.md](../research/smart_zone/placebo/PROTOCOL.md)). Lookahead checks passed in all three: truncating the series or corrupting future bars left earlier zones and signals unchanged, entries occur only at the next open after confirmation, and stops win same-bar ties ([test_no_lookahead.py](../research/smart_zone/mtf/test_no_lookahead.py); [tests_no_lookahead.py](../research/smart_zone/same_tf/tests_no_lookahead.py); [truncation_check.py](../research/smart_zone/placebo/truncation_check.py)).

The holdouts are clean but not pristine. The user's earlier strategy studies used the same 2026 months ([ob_timeframe_protocol.md](../research/ob_timeframe_protocol.md)). The placebo study's development tables also printed some holdout-period rates for one configuration before its holdout run, although no parameter changed afterward ([PROTOCOL.md](../research/smart_zone/placebo/PROTOCOL.md)). These contaminations would favour finding an edge, and none appeared.

The reconstruction is the main threat to validity. The [TradingView page](https://www.tradingview.com/script/oK06JCrx-Smart-Zone-Pro-Abusuhil/) publishes the mechanics and presets but not pivot length, decay, merge constants or the strength scale. (One workstream's search failed to find this page and reported none existed; the placebo workstream located it.) The author makes no performance claims and says the tool generates no buy or sell signals, so these tests evaluate a use of the indicator that its author does not promise. Sensitivity runs reduce this risk without removing it: **24 single-assumption changes left the same-timeframe loss intact, with 1 of 240 test cells positive** ([sensitivity.csv](../research/smart_zone/same_tf/results/sensitivity.csv)). No zones were compared against the indicator's actual chart output.

## Real zones attract no more reaction than placebo levels

The placebo study asks the question that precedes any trading rule: does price respect these zones more than other levels? Against placebos matched for width and distance, **none of the 24 valid holdout comparisons across 5m, 15m, 1h and 4h is positive and significant after correction** ([f1.csv](../research/smart_zone/placebo/output/binance_balanced_p5/results_holdout/f1.csv)). Raw reaction rates look attractive, around 53-64%, but placebos score the same because the failure barrier sits farther away than the success barrier. A quoted "60% zone hold rate" carries no information without a placebo beside it.

| Timeframe | Touch events (X=1 ATR) | Real reaction rate | Random-offset placebo | Real minus placebo (95% CI) |
|---|---|---|---|---|
| 5m | 18,067 | 57.1% | 57.3% | -0.20pp (-0.79, +0.40) |
| 15m | 5,961 | 59.5% | 59.6% | -0.12pp (-1.11, +0.86) |
| 1h | 1,306 | 59.0% | 61.4% | -2.39pp (-5.32, +0.54) |
| 4h | 373 | 56.3% | 57.6% | -1.26pp (-7.09, +4.58) |

The star rating fails the same control. Reaction rates climb with stars, touches and flip status, yet placebos inheriting the same labels climb equally, and **0 of 48 excess-slope tests survive Holm correction** ([f2.csv](../research/smart_zone/placebo/output/binance_balanced_p5/results_holdout/f2.csv)). Mean width grows from about 0.13 ATR at one star to about 0.85 ATR at four, so the score largely measures geometry. The real script's unpublished width penalty could weaken that channel, so this reading applies most firmly to the reconstruction. The strategy results agree: the Stars>=2 filter changed net R by about zero and first-touch-only zones were worse ([filter_marginals.csv](../research/smart_zone/mtf/results/filter_marginals.csv)).

The chart's persuasive look probably has a different source. Removing pivot confirmation lag raised reaction rates by at most 1.25pp ([hindsight.csv](../research/smart_zone/placebo/output/binance_balanced_p5/results_holdout/hindsight.csv)), so plotting lag explains little. A likelier explanation, which is inference because the code is closed, is that today's selected zones are drawn across bars that already happened. TradingView's documentation warns about closely related [pivot-plotting and historical-versus-realtime differences](https://tradingview.com/pine-script-docs/concepts/repainting).

Published work offers a useful yardstick. Osler's FX study found published levels beat arbitrary levels by about 4-5pp, using a much looser 15-minute criterion, and left profitability untested ([Osler 2000](https://resources.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf)). The 5m and 15m intervals here rule out anything near that size. The 4h interval cannot.

## Costs turn a flat signal into a loss, worst on short timeframes

Same-timeframe rejection trading loses at every timeframe and preset, and **0 of 121 timeframe/preset/zone/star cells with at least 30 trades were positive in 2026** at the 1R baseline ([cube_R1_b025.csv](../research/smart_zone/same_tf/results/cube_R1_b025.csv)). The gradient is mechanical. A 0.14% round trip against a median stop costs 0.80R at 5m, 0.42R at 15m, 0.28R at 30m, 0.20R at 1h and 0.09R at 4h ([analyze.py](../research/smart_zone/same_tf/analyze.py)).

| Same-timeframe baseline, Balanced, 2026 | Trades | Win rate | Net R, zero cost | Net R, maker entry | Net R, base cost | Sized return (0.5% risk, max 3x) |
|---|---|---|---|---|---|---|
| 5m | 4,408 | 32.2% | -0.023 | -0.655 | -1.006 | -100% |
| 15m | 1,356 | 46.0% | -0.035 | -0.346 | -0.519 | -96.4% |
| 30m | 703 | 46.1% | -0.077 | -0.276 | -0.387 | -74.5% |
| 1h | 323 | 43.0% | -0.136 | -0.274 | -0.351 | -43.5% |
| 4h | 96 | 49.0% | -0.021 | -0.081 | -0.114 | -5.4% |

Sources: [baseline_selected_ci.csv](../research/smart_zone/same_tf/results/baseline_selected_ci.csv); [baseline_costs.csv](../research/smart_zone/same_tf/results/baseline_costs.csv).

Zero-cost results are at or below zero in every row, so cheaper execution alone cannot rescue this baseline. Maker entry helps but stays negative, even though it assumes guaranteed fills at the next open with no adverse selection. Higher-timeframe zones with lower-timeframe triggers fare no better: **39 of 40 unfiltered Balanced cells were negative in 2026**, the exception being 4h/1h at 2R with +0.002R ([all_variants_all_periods.csv](../research/smart_zone/mtf/results/all_variants_all_periods.csv)). Tightening entries on lower timeframes shrinks the stop and raises the cost burden, which offsets any precision gained.

Exits redistribute the loss without removing it. Mean net R stayed between -0.15 and -0.26 for all five exits across all three periods in the multi-timeframe grid ([exit_marginals.csv](../research/smart_zone/mtf/results/exit_marginals.csv)), and between -0.35 and -0.57 for all seven in the same-timeframe grid ([exits_all.csv](../research/smart_zone/same_tf/results/exits_all.csv)). Random entries with identical side, stop, target and time limit perform the same: rejection signals beat them by -0.002R, -0.054R, -0.012R and -0.046R on 5m, 15m, 1h and 4h, none significant ([f3.csv](../research/smart_zone/placebo/output/binance_balanced_p5/results_holdout/f3.csv)).

## Every rule that won in 2024-2025 failed in 2026

The grid searches found winners during development, as searches of this size always do, and the winners did not transfer. The multi-timeframe search of 1,040 variants returned a **White reality check p of 0.978** and no variant at BH q<10% ([dev_summary.json](../research/smart_zone/mtf/results/dev_summary.json)). The same-timeframe search of 3,157 tested variants had a smallest raw p of 0.113, so it fails even before correction ([analyze.log](../research/smart_zone/same_tf/results/analyze.log)).

| Rule frozen on 2024-2025 | Train R | Validation R | 2026 trades | 2026 net R [95% CI] | Beats random entry? (p) |
|---|---|---|---|---|---|
| 4h/5m Balanced, ADX<=25, ATR trail | +0.133 | +0.063 | 133 | -0.159 [-0.44, +0.14] | No (0.415) |
| 4h/15m Balanced, Asia session, ATR trail | +0.028 | +0.067 | 93 | -0.018 [-0.34, +0.33] | No (0.098) |
| 4h/1h Strict, ADX<=25, ATR trail | +0.001 | +0.121 | 66 | -0.241 [-0.54, +0.06] | No (0.723) |
| 30m Strict, Resistance, 3-star, time exit | +0.184 | +0.488 | 44 | -0.155 [-0.99, +1.24] | Not run |
| 4h Strict, Flip, time exit | +0.495 | +0.325 | 33 | -0.477 [-1.15, +1.04] | Not run |

Sources: [finalists_baselines.csv](../research/smart_zone/mtf/results/finalists_baselines.csv); [baseline_selected_ci.csv](../research/smart_zone/same_tf/results/baseline_selected_ci.csv).

Rolling re-selection agrees that the signal is weak. Same-timeframe quarterly walk-forward from 2025 returned -0.138R on 15m, +0.011R on 30m, -0.468R on 1h and -0.323R on 4h ([walkforward.csv](../research/smart_zone/same_tf/results/walkforward.csv)). The multi-timeframe walk-forward returned **+0.067R on 96 trades, but with a CI of -0.28 to +0.43** ([walkforward_summary.json](../research/smart_zone/mtf/results/walkforward_summary.json)). That is the most favourable out-of-sample figure produced, and it cannot be told apart from zero.

Delta replication points the same way. All seven multi-timeframe rules lost on Delta 2026, from -0.086R to -0.403R ([delta_replication.csv](../research/smart_zone/mtf/results/delta_replication.csv)), as did the same-timeframe 5m to 1h baselines ([delta_replication.csv](../research/smart_zone/same_tf/results/delta_replication.csv)). Delta's gaps left too few continuous bars for same-timeframe 4h, and the replication excludes funding.

This also reframes the earlier high-win-rate work. The closest analogue to the [earlier 81.6% OB-rejection study](/Users/ajaybaburaj/.claude/projects/-Users-ajaybaburaj-Documents-ajay-crypto/memory/ob-rejection-strategy-study.md), 4h/15m with EMA200+ADX<=25 at 0.5R, won 70.5% of trades on Binance and still lost -0.083R; on Delta it won 52.6% and lost -0.321R. Zone definitions, venue and costs differ, so this is not a direct refutation. It does show why a 0.5R target's win rate proves little: the geometry alone implies about two-thirds wins before costs.

## The surviving leads sit on 4h, where the data cannot decide

The strongest case for continuing is statistical power at 4h. Costs there are small, and a real edge of about **4.4pp would break even on the fade model, a size inside the 4h confidence interval** but near Osler's FX effect, while 5m would need about 35pp ([breakeven.csv](../research/smart_zone/placebo/output/binance_balanced_p5/results_holdout/breakeven.csv)). With about 370 touch events, the placebo test cannot exclude that. Its point estimate, however, is -1.3pp, and the best fade-model gross return in the study (+0.066% at 4h, X=2) still falls short of 0.14% costs.

Three leads are worth recording as hypotheses, not results. EMA200 was the only filter with a consistent sign, improving 60-92% of cells in each period, though most filtered test cells stayed negative ([filter_marginals.csv](../research/smart_zone/mtf/results/filter_marginals.csv)). A variant, 4h/5m Balanced with EMA200+ADX<=25 and ATR trail, passed development and earned +0.282R on 55 test trades but ranked below another variant under the frozen rule, so promoting it now would be selecting on the holdout ([all_variants_all_periods.csv](../research/smart_zone/mtf/results/all_variants_all_periods.csv)). And longs beat shorts on several finalists, such as +0.294R against -0.244R for the Asia rule ([sides.csv](../research/smart_zone/mtf/results/sides.csv)), yet the same-timeframe baselines show no such asymmetry ([slices.csv](../research/smart_zone/same_tf/results/slices.csv)), so path dependence is the simpler explanation. Comparable best-in-test results, such as the 1h Strict flip rule at +0.386R on 92 trades, lost in both 2024 and 2025 ([stage2_metrics.csv](../research/smart_zone/same_tf/results/stage2_metrics.csv)).

The wider literature gives no reason to expect otherwise. Sullivan, Timmermann and White found "scant evidence" of value in technical rules out of sample once data snooping was addressed ([1999 paper](https://bashtage.github.io/kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf)), and Hudson and Urquhart's roughly 15,000-rule crypto test reports "no predictability for Bitcoin in the out-of-sample period" ([abstract only](https://centaur.reading.ac.uk/85715)). No peer-reviewed test of pivot-cluster zones on BTC, or independent test of this script, turned up. Early BTC work does find profitable intraday rules, but in a 2013-2017 thesis whose profits declined over time ([Erasmus thesis](https://thesis.eur.nl/pub/41546/)).

## Conclusion

Stop treating Smart Zone Pro as a signal source. On this evidence its zones are a reasonable visual summary of past swing areas, which is also all the author claims. The placebo finding matters more than any backtest figure, because no exit, filter or fee tweak can extract an edge from levels that behave like random ones. Further parameter search on the same three years would only add to the 5,600-plus variants that failed.

Two inexpensive steps would resolve what remains open. Export the actual indicator's zones and compare them against the reconstruction, since that is the only route to overturning the verdict. If they differ materially, rerun the placebo test first and the strategy grid only if real zones beat placebos. Otherwise, pick one 4h rule now, freeze it, and forward-paper-trade it through the existing paper backend with a pre-set trade count and kill criterion, accepting that a 4h rule produces perhaps 50-150 trades a year and that the result will take time to mean anything.
