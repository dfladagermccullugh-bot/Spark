# Stall-alarm backtest

- As-of date: 2026-11-23 (UTC midnight)
- Branches: default checkout only
- Reproduce: `spark backtest /workspace/spark-backtest-repos/Kaban-Plus-Ultra /workspace/spark-backtest-repos/MCP-Bridge-Dashboard /workspace/spark-backtest-repos/Moth /workspace/spark-backtest-repos/NutriCostOptimzer /workspace/spark-backtest-repos/Open-Island-Transit-Data /workspace/spark-backtest-repos/Spark /workspace/spark-backtest-repos/ThoughStream /workspace/spark-backtest-repos/Verity /workspace/spark-backtest-repos/everyday_watcher /workspace/spark-backtest-repos/reel-to-md /workspace/spark-backtest-repos/tarot_deck --multiplier 2 4 8 --as-of 2026-11-23`

Shares use resolved (non-censored) alerts as the denominator, shown as k/n.

## Pooled

| Setting | Commits | Active wks | Alerts | Alerts/active wk | resumed_24h | resumed_7d | resumed_14d | real_stall | censored | Resumed within 24h | Resumed within 7d | Real-stall precision | Missed | Median h to alert |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Pooled x2 | 396 | 18 | 61 | 3.39 | 44 | 0 | 1 | 12 | 4 | 77% (44/57) | 77% (44/57) | 21% (12/57) | 0 | 0.6 |
| Pooled x4 | 396 | 18 | 45 | 2.50 | 28 | 0 | 1 | 12 | 4 | 68% (28/41) | 68% (28/41) | 29% (12/41) | 0 | 1.2 |
| Pooled x8 | 396 | 18 | 39 | 2.17 | 23 | 0 | 1 | 12 | 3 | 64% (23/36) | 64% (23/36) | 33% (12/36) | 0 | 2.4 |

## Per repo, multiplier x2

| Repo | Commits | Active wks | Alerts | Alerts/active wk | resumed_24h | resumed_7d | resumed_14d | real_stall | censored | Resumed within 24h | Resumed within 7d | Real-stall precision | Missed | Median h to alert |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Kaban-Plus-Ultra | 78 | 1 | 11 | 11.00 | 10 | 0 | 0 | 1 | 0 | 91% (10/11) | 91% (10/11) | 9% (1/11) | 0 | 2.0 |
| MCP-Bridge-Dashboard | 8 | 1 | 2 | 2.00 | 1 | 0 | 0 | 1 | 0 | 50% (1/2) | 50% (1/2) | 50% (1/2) | 0 | 0.5 |
| Moth | 23 | 1 | 4 | 4.00 | 3 | 0 | 0 | 1 | 0 | 75% (3/4) | 75% (3/4) | 25% (1/4) | 0 | 0.2 |
| NutriCostOptimzer | 23 | 2 | 5 | 2.50 | 3 | 0 | 0 | 2 | 0 | 60% (3/5) | 60% (3/5) | 40% (2/5) | 0 | 0.4 |
| Open-Island-Transit-Data | 95 | 1 | 6 | 6.00 | 5 | 0 | 0 | 0 | 1 | 100% (5/5) | 100% (5/5) | 0% (0/5) | 0 | 1.8 |
| Spark | 16 | 2 | 3 | 1.50 | 1 | 0 | 0 | 1 | 1 | 50% (1/2) | 50% (1/2) | 50% (1/2) | 0 | 0.4 |
| ThoughStream | 3 | 1 | 1 | 1.00 | 0 | 0 | 0 | 1 | 0 | 0% (0/1) | 0% (0/1) | 100% (1/1) | 0 | 0.6 |
| Verity | 140 | 6 | 23 | 3.83 | 18 | 0 | 1 | 3 | 1 | 82% (18/22) | 82% (18/22) | 14% (3/22) | 0 | 0.2 |
| everyday_watcher | 4 | 1 | 3 | 3.00 | 2 | 0 | 0 | 1 | 0 | 67% (2/3) | 67% (2/3) | 33% (1/3) | 0 | 0.0 |
| reel-to-md | 2 | 1 | 1 | 1.00 | 0 | 0 | 0 | 1 | 0 | 0% (0/1) | 0% (0/1) | 100% (1/1) | 0 | 14.8 |
| tarot_deck | 4 | 1 | 2 | 2.00 | 1 | 0 | 0 | 0 | 1 | 100% (1/1) | 100% (1/1) | 0% (0/1) | 0 | 1.6 |

## Per repo, multiplier x4

| Repo | Commits | Active wks | Alerts | Alerts/active wk | resumed_24h | resumed_7d | resumed_14d | real_stall | censored | Resumed within 24h | Resumed within 7d | Real-stall precision | Missed | Median h to alert |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Kaban-Plus-Ultra | 78 | 1 | 8 | 8.00 | 7 | 0 | 0 | 1 | 0 | 88% (7/8) | 88% (7/8) | 12% (1/8) | 0 | 3.8 |
| MCP-Bridge-Dashboard | 8 | 1 | 2 | 2.00 | 1 | 0 | 0 | 1 | 0 | 50% (1/2) | 50% (1/2) | 50% (1/2) | 0 | 1.0 |
| Moth | 23 | 1 | 3 | 3.00 | 2 | 0 | 0 | 1 | 0 | 67% (2/3) | 67% (2/3) | 33% (1/3) | 0 | 0.4 |
| NutriCostOptimzer | 23 | 2 | 4 | 2.00 | 2 | 0 | 0 | 2 | 0 | 50% (2/4) | 50% (2/4) | 50% (2/4) | 0 | 0.8 |
| Open-Island-Transit-Data | 95 | 1 | 5 | 5.00 | 4 | 0 | 0 | 0 | 1 | 100% (4/4) | 100% (4/4) | 0% (0/4) | 0 | 3.6 |
| Spark | 16 | 2 | 2 | 1.00 | 0 | 0 | 0 | 1 | 1 | 0% (0/1) | 0% (0/1) | 100% (1/1) | 0 | 48.4 |
| ThoughStream | 3 | 1 | 1 | 1.00 | 0 | 0 | 0 | 1 | 0 | 0% (0/1) | 0% (0/1) | 100% (1/1) | 0 | 1.2 |
| Verity | 140 | 6 | 14 | 2.33 | 9 | 0 | 1 | 3 | 1 | 69% (9/13) | 69% (9/13) | 23% (3/13) | 0 | 1.2 |
| everyday_watcher | 4 | 1 | 3 | 3.00 | 2 | 0 | 0 | 1 | 0 | 67% (2/3) | 67% (2/3) | 33% (1/3) | 0 | 0.0 |
| reel-to-md | 2 | 1 | 1 | 1.00 | 0 | 0 | 0 | 1 | 0 | 0% (0/1) | 0% (0/1) | 100% (1/1) | 0 | 29.6 |
| tarot_deck | 4 | 1 | 2 | 2.00 | 1 | 0 | 0 | 0 | 1 | 100% (1/1) | 100% (1/1) | 0% (0/1) | 0 | 3.2 |

## Per repo, multiplier x8

| Repo | Commits | Active wks | Alerts | Alerts/active wk | resumed_24h | resumed_7d | resumed_14d | real_stall | censored | Resumed within 24h | Resumed within 7d | Real-stall precision | Missed | Median h to alert |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Kaban-Plus-Ultra | 78 | 1 | 6 | 6.00 | 5 | 0 | 0 | 1 | 0 | 83% (5/6) | 83% (5/6) | 17% (1/6) | 0 | 8.4 |
| MCP-Bridge-Dashboard | 8 | 1 | 2 | 2.00 | 1 | 0 | 0 | 1 | 0 | 50% (1/2) | 50% (1/2) | 50% (1/2) | 0 | 2.0 |
| Moth | 23 | 1 | 3 | 3.00 | 2 | 0 | 0 | 1 | 0 | 67% (2/3) | 67% (2/3) | 33% (1/3) | 0 | 0.8 |
| NutriCostOptimzer | 23 | 2 | 4 | 2.00 | 2 | 0 | 0 | 2 | 0 | 50% (2/4) | 50% (2/4) | 50% (2/4) | 0 | 1.6 |
| Open-Island-Transit-Data | 95 | 1 | 5 | 5.00 | 4 | 0 | 0 | 0 | 1 | 100% (4/4) | 100% (4/4) | 0% (0/4) | 0 | 7.2 |
| Spark | 16 | 2 | 1 | 0.50 | 0 | 0 | 0 | 1 | 0 | 0% (0/1) | 0% (0/1) | 100% (1/1) | 0 | 1.6 |
| ThoughStream | 3 | 1 | 1 | 1.00 | 0 | 0 | 0 | 1 | 0 | 0% (0/1) | 0% (0/1) | 100% (1/1) | 0 | 2.4 |
| Verity | 140 | 6 | 11 | 1.83 | 6 | 0 | 1 | 3 | 1 | 60% (6/10) | 60% (6/10) | 30% (3/10) | 0 | 2.4 |
| everyday_watcher | 4 | 1 | 3 | 3.00 | 2 | 0 | 0 | 1 | 0 | 67% (2/3) | 67% (2/3) | 33% (1/3) | 0 | 0.0 |
| reel-to-md | 2 | 1 | 1 | 1.00 | 0 | 0 | 0 | 1 | 0 | 0% (0/1) | 0% (0/1) | 100% (1/1) | 0 | 59.2 |
| tarot_deck | 4 | 1 | 2 | 2.00 | 1 | 0 | 0 | 0 | 1 | 100% (1/1) | 100% (1/1) | 0% (0/1) | 0 | 6.4 |

