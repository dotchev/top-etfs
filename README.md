# Top US ETFs by Sharpe Ratio

A script that ranks US-listed ETFs by their 3-year Sharpe ratio, using [Portfolio Visualizer's fund-screener](https://www.portfoliovisualizer.com/fund-screener).

## Setup (once)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
source .venv/bin/activate                # if not already active

python top_etfs.py                       # default: top 300 -> top_etfs.csv
python top_etfs.py -l 500                # top 500
python top_etfs.py -o my.csv
python top_etfs.py --help
```

### CLI

| Flag | Default | Description |
|---|---|---|
| `-l`, `--limit` | `300` | Target row count. Server returns 15 rows/page, so the actual count may overshoot the limit; **all fetched rows are kept**. |
| `-o`, `--output` | `top_etfs.csv` | Output CSV path. |
| `-h`, `--help` | – | Show usage and exit. |

## How it works

1. POSTs the screener form with `fundType=ETF` and `performanceHistoryPeriod=all`.
2. Pages through the DataTables AJAX endpoint with **server-side sort by Sharpe descending**, so we fetch only ~LIMIT rows instead of the full ~2,640. The server hard-caps responses at 15 rows per page; the script paces 2.5s between requests with exponential backoff on HTTP 429.
3. Parses the 20 returned columns and writes the CSV ranked by Sharpe.

Typical runtime: ~60s for 300 rows, ~110s for 600 rows.

## CSV columns

All columns come from Portfolio Visualizer's screener response (with light cleanup — HTML link stripping, `%`/suffix removal). Rows are written in PV's response order (3Y Sharpe descending), so file position is the ranking.

All Sharpe/Sortino/Volatility figures are 3-year values from PV (trailing 36 months of monthly returns).

| Column | Meaning |
|---|---|
| `Ticker`, `Name`, `AssetClass`, `Category` | Identifiers |
| `Sharpe` | 3-year Sharpe ratio (the ranking key) |
| `Sortino` | 3-year Sortino ratio |
| `Volatility_pct` | Annualized stdev of monthly returns over the trailing 36 months, % |
| `Return_YTD_pct`, `Return_1Y_pct`, `Return_3Y_pct`, `Return_5Y_pct` | Additional return windows |
| `YieldTTM_pct`, `ExpenseRatio_pct` | Income & cost |
| `Assets_USD` | AUM in USD |
| `Inception` | ETF inception date |

## Verification

The scraped data was cross-checked against an independent recomputation from yfinance adjusted-close prices for SMH (VanEck Semiconductor ETF) over May 2023 → May 2026:

| Metric | PV scraped | Recomputed | Δ |
|---|---|---|---|
| 3Y Volatility | 30.34% | 29.78% | −0.56 pp |
| 3Y Annualized Return | 60.75% | 58.46% | −2.29 pp |
| 3Y Sharpe (rf=4.0%) | 1.58 | 1.577 | ~0 |

The Sharpe match is essentially exact when the risk-free rate is 4%, confirming PV's methodology. Small return/volatility gaps are attributable to data-source differences (NAV vs adjusted close) and cutoff-date alignment.

## Files in this directory

| File | Purpose |
|---|---|
| `top_etfs.py` | The single end-to-end script |
| `requirements.txt` | Pinned pip dependencies |
| `top_etfs.csv` | Example output: default run (top 300 ETFs by 3Y Sharpe) |
| `README.md` | This file |
| `.venv/` | Project-local Python virtual environment (gitignored) |

## Caveats

- **Universe**: All US-listed ETFs that Portfolio Visualizer tracks. PV requires at least 3 months of history for an ETF to appear in the screener at all, so brand-new launches are excluded.
