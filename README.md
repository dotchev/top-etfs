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
| `-d`, `--delay` | `2.5` | Seconds between requests. Doubled automatically (up to 30s) on each HTTP 429. |
| `-h`, `--help` | – | Show usage and exit. |

## How it works

1. POSTs the screener form with `fundType=ETF` and `performanceHistoryPeriod=all`.
2. Pages through the DataTables AJAX endpoint with **server-side sort by Sharpe descending**, so we fetch only ~LIMIT rows instead of the full ~2,640. The server hard-caps responses at 15 rows per page; the script paces 2.5s between requests (`--delay`). On HTTP 429 it waits (honoring `Retry-After` if sent), doubles the pacing for the rest of the run, and prints a `[rate-limited]` summary at the end suggesting a `--delay` for next time.
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
| `Return_YTD_pct`, `Return_1Y_pct`, `Return_3Y_pct`, `Return_5Y_pct` | Total returns, %. YTD and 1Y are simple period returns; 3Y and 5Y are **annualized** |
| `YieldTTM_pct`, `ExpenseRatio_pct` | Income & cost |
| `Assets_USD` | AUM in USD |
| `Inception` | ETF inception date |


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
