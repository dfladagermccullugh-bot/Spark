# Stall-alarm backtest

- As-of date: 2026-11-23 (UTC midnight)
- Branches: all branches (--all)
- Reproduce: `spark backtest /workspace/spark-backtest-repos/Kaban-Plus-Ultra /workspace/spark-backtest-repos/MCP-Bridge-Dashboard /workspace/spark-backtest-repos/Moth /workspace/spark-backtest-repos/NutriCostOptimzer /workspace/spark-backtest-repos/Open-Island-Transit-Data /workspace/spark-backtest-repos/Spark /workspace/spark-backtest-repos/ThoughStream /workspace/spark-backtest-repos/Verity /workspace/spark-backtest-repos/everyday_watcher /workspace/spark-backtest-repos/reel-to-md /workspace/spark-backtest-repos/tarot_deck --multiplier 2 4 8 --all-branches --as-of 2026-11-23`

Shares use resolved (non-censored) alerts as the denominator, shown as k/n.

## Pooled

| Setting | Commits | Active wks | Alerts | Alerts/active wk | resumed_24h | resumed_7d | resumed_14d | real_stall | censored | Resumed within 24h | Resumed within 7d | Real-stall precision | Missed | Median h to alert |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Pooled x2 | 441 | 18 | 71 | 3.94 | 54 | 0 | 1 | 12 | 4 | 81% (54/67) | 81% (54/67) | 18% (12/67) | 0 | 0.4 |
| Pooled x4 | 441 | 18 | 55 | 3.06 | 38 | 0 | 1 | 12 | 4 | 75% (38/51) | 75% (38/51) | 24% (12/51) | 0 | 1.2 |
| Pooled x8 | 441 | 18 | 47 | 2.61 | 30 | 0 | 1 | 12 | 4 | 70% (30/43) | 70% (30/43) | 28% (12/43) | 0 | 2.4 |

## Per repo, multiplier x2

| Repo | Commits | Active wks | Alerts | Alerts/active wk | resumed_24h | resumed_7d | resumed_14d | real_stall | censored | Resumed within 24h | Resumed within 7d | Real-stall precision | Missed | Median h to alert |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Kaban-Plus-Ultra | 82 | 1 | 11 | 11.00 | 10 | 0 | 0 | 1 | 0 | 91% (10/11) | 91% (10/11) | 9% (1/11) | 0 | 1.8 |
| MCP-Bridge-Dashboard | 8 | 1 | 2 | 2.00 | 1 | 0 | 0 | 1 | 0 | 50% (1/2) | 50% (1/2) | 50% (1/2) | 0 | 0.5 |
| Moth | 23 | 1 | 4 | 4.00 | 3 | 0 | 0 | 1 | 0 | 75% (3/4) | 75% (3/4) | 25% (1/4) | 0 | 0.2 |
| NutriCostOptimzer | 23 | 2 | 5 | 2.50 | 3 | 0 | 0 | 2 | 0 | 60% (3/5) | 60% (3/5) | 40% (2/5) | 0 | 0.4 |
| Open-Island-Transit-Data | 125 | 1 | 9 | 9.00 | 8 | 0 | 0 | 0 | 1 | 100% (8/8) | 100% (8/8) | 0% (0/8) | 0 | 1.6 |
| Spark | 26 | 2 | 10 | 5.00 | 8 | 0 | 0 | 1 | 1 | 89% (8/9) | 89% (8/9) | 11% (1/9) | 0 | 0.0 |
| ThoughStream | 3 | 1 | 1 | 1.00 | 0 | 0 | 0 | 1 | 0 | 0% (0/1) | 0% (0/1) | 100% (1/1) | 0 | 0.6 |
| Verity | 141 | 6 | 23 | 3.83 | 18 | 0 | 1 | 3 | 1 | 82% (18/22) | 82% (18/22) | 14% (3/22) | 0 | 0.2 |
| everyday_watcher | 4 | 1 | 3 | 3.00 | 2 | 0 | 0 | 1 | 0 | 67% (2/3) | 67% (2/3) | 33% (1/3) | 0 | 0.0 |
| reel-to-md | 2 | 1 | 1 | 1.00 | 0 | 0 | 0 | 1 | 0 | 0% (0/1) | 0% (0/1) | 100% (1/1) | 0 | 14.8 |
| tarot_deck | 4 | 1 | 2 | 2.00 | 1 | 0 | 0 | 0 | 1 | 100% (1/1) | 100% (1/1) | 0% (0/1) | 0 | 1.6 |

## Per repo, multiplier x4

| Repo | Commits | Active wks | Alerts | Alerts/active wk | resumed_24h | resumed_7d | resumed_14d | real_stall | censored | Resumed within 24h | Resumed within 7d | Real-stall precision | Missed | Median h to alert |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Kaban-Plus-Ultra | 82 | 1 | 8 | 8.00 | 7 | 0 | 0 | 1 | 0 | 88% (7/8) | 88% (7/8) | 12% (1/8) | 0 | 3.8 |
| MCP-Bridge-Dashboard | 8 | 1 | 2 | 2.00 | 1 | 0 | 0 | 1 | 0 | 50% (1/2) | 50% (1/2) | 50% (1/2) | 0 | 1.0 |
| Moth | 23 | 1 | 3 | 3.00 | 2 | 0 | 0 | 1 | 0 | 67% (2/3) | 67% (2/3) | 33% (1/3) | 0 | 0.4 |
| NutriCostOptimzer | 23 | 2 | 4 | 2.00 | 2 | 0 | 0 | 2 | 0 | 50% (2/4) | 50% (2/4) | 50% (2/4) | 0 | 0.8 |
| Open-Island-Transit-Data | 125 | 1 | 8 | 8.00 | 7 | 0 | 0 | 0 | 1 | 100% (7/7) | 100% (7/7) | 0% (0/7) | 0 | 3.0 |
| Spark | 26 | 2 | 9 | 4.50 | 7 | 0 | 0 | 1 | 1 | 88% (7/8) | 88% (7/8) | 12% (1/8) | 0 | 0.0 |
| ThoughStream | 3 | 1 | 1 | 1.00 | 0 | 0 | 0 | 1 | 0 | 0% (0/1) | 0% (0/1) | 100% (1/1) | 0 | 1.2 |
| Verity | 141 | 6 | 14 | 2.33 | 9 | 0 | 1 | 3 | 1 | 69% (9/13) | 69% (9/13) | 23% (3/13) | 0 | 1.2 |
| everyday_watcher | 4 | 1 | 3 | 3.00 | 2 | 0 | 0 | 1 | 0 | 67% (2/3) | 67% (2/3) | 33% (1/3) | 0 | 0.0 |
| reel-to-md | 2 | 1 | 1 | 1.00 | 0 | 0 | 0 | 1 | 0 | 0% (0/1) | 0% (0/1) | 100% (1/1) | 0 | 29.6 |
| tarot_deck | 4 | 1 | 2 | 2.00 | 1 | 0 | 0 | 0 | 1 | 100% (1/1) | 100% (1/1) | 0% (0/1) | 0 | 3.2 |

## Per repo, multiplier x8

| Repo | Commits | Active wks | Alerts | Alerts/active wk | resumed_24h | resumed_7d | resumed_14d | real_stall | censored | Resumed within 24h | Resumed within 7d | Real-stall precision | Missed | Median h to alert |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Kaban-Plus-Ultra | 82 | 1 | 6 | 6.00 | 5 | 0 | 0 | 1 | 0 | 83% (5/6) | 83% (5/6) | 17% (1/6) | 0 | 8.0 |
| MCP-Bridge-Dashboard | 8 | 1 | 2 | 2.00 | 1 | 0 | 0 | 1 | 0 | 50% (1/2) | 50% (1/2) | 50% (1/2) | 0 | 2.0 |
| Moth | 23 | 1 | 3 | 3.00 | 2 | 0 | 0 | 1 | 0 | 67% (2/3) | 67% (2/3) | 33% (1/3) | 0 | 0.8 |
| NutriCostOptimzer | 23 | 2 | 4 | 2.00 | 2 | 0 | 0 | 2 | 0 | 50% (2/4) | 50% (2/4) | 50% (2/4) | 0 | 1.6 |
| Open-Island-Transit-Data | 125 | 1 | 5 | 5.00 | 4 | 0 | 0 | 0 | 1 | 100% (4/4) | 100% (4/4) | 0% (0/4) | 0 | 4.8 |
| Spark | 26 | 2 | 9 | 4.50 | 7 | 0 | 0 | 1 | 1 | 88% (7/8) | 88% (7/8) | 12% (1/8) | 0 | 0.0 |
| ThoughStream | 3 | 1 | 1 | 1.00 | 0 | 0 | 0 | 1 | 0 | 0% (0/1) | 0% (0/1) | 100% (1/1) | 0 | 2.4 |
| Verity | 141 | 6 | 11 | 1.83 | 6 | 0 | 1 | 3 | 1 | 60% (6/10) | 60% (6/10) | 30% (3/10) | 0 | 2.4 |
| everyday_watcher | 4 | 1 | 3 | 3.00 | 2 | 0 | 0 | 1 | 0 | 67% (2/3) | 67% (2/3) | 33% (1/3) | 0 | 0.0 |
| reel-to-md | 2 | 1 | 1 | 1.00 | 0 | 0 | 0 | 1 | 0 | 0% (0/1) | 0% (0/1) | 100% (1/1) | 0 | 59.2 |
| tarot_deck | 4 | 1 | 2 | 2.00 | 1 | 0 | 0 | 0 | 1 | 100% (1/1) | 100% (1/1) | 0% (0/1) | 0 | 6.4 |

