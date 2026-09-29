"""Fetch the top US ETFs by 3-year Sharpe ratio from Portfolio Visualizer.

Uses the fund-screener DataTables AJAX endpoint with server-side sort by
Sharpe descending, so we pull only ~LIMIT rows (~LIMIT/15 pages) instead
of the full ~2,640. The page size is fixed by the server at 15, so the
actual row count may overshoot LIMIT by a few; all fetched rows are kept.
"""
import argparse
import csv
import math
import re
import sys
import time

import requests


# ---------- constants ----------

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
BASE = "https://www.portfoliovisualizer.com/fund-screener"

# Column layout returned by the screener's DataTable (20 data columns).
COLUMNS = [
    "Ticker", "Name", "AssetClass", "Category",
    "YTD", "Return_1Y", "Return_3Y", "Return_5Y",
    "Sharpe", "Sortino", "Volatility", "TrackingError",
    "InformationRatio", "UpsideCapture", "DownsideCapture",
    "YieldSEC", "YieldTTM", "ExpenseRatio", "Assets", "Inception",
]
SHARPE_COL_IDX = COLUMNS.index("Sharpe")  # = 8

PAGE = 15                # server hard-caps the response at 15 rows
BASE_DELAY = 2.5         # default pacing between requests (--delay)
MAX_DELAY = 30.0         # cap for adaptive pacing after 429s
MAX_429_BEFORE_REOPEN = 3

LINK_RE = re.compile(r'<a[^>]*>([^<]*)</a>')
SUFFIX = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


# ---------- parsing helpers ----------

def strip_link(s):
    m = LINK_RE.search(s or "")
    return (m.group(1) if m else (s or "")).strip()


def parse_pct(s):
    if not s or s in ("--", "N/A"):
        return math.nan
    s = s.strip().rstrip("%").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return math.nan


def parse_num(s):
    if not s or s in ("--", "N/A"):
        return math.nan
    try:
        return float(s.strip().replace(",", ""))
    except ValueError:
        return math.nan


def parse_assets(s):
    if not s or s in ("--", "N/A"):
        return math.nan
    s = s.strip().replace(",", "")
    m = re.match(r"^([0-9.]+)\s*([KMBT])?$", s, re.I)
    if not m:
        try:
            return float(s)
        except ValueError:
            return math.nan
    return float(m.group(1)) * SUFFIX.get((m.group(2) or "").upper(), 1.0)


# ---------- HTTP layer ----------

def open_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json, text/javascript, */*"})
    s.get(BASE, timeout=30)
    form = {
        "fundType": "2",                   # ETF
        "assetClass": "",
        "categories": "",
        "benchmarkName": "",
        "performanceHistoryPeriod": "-1",  # all (no minimum-history filter)
        "expenseRatio": "-1",
    }
    s.post(BASE, data=form, timeout=60)
    return s


def make_payload(start, draw, sort_col, sort_dir):
    p = {
        "draw": draw, "start": start, "length": PAGE,
        "search[value]": "", "search[regex]": "false",
        "order[0][column]": sort_col, "order[0][dir]": sort_dir,
    }
    for i in range(len(COLUMNS)):
        p[f"columns[{i}][data]"] = str(i)
        p[f"columns[{i}][name]"] = ""
        p[f"columns[{i}][searchable]"] = "true"
        p[f"columns[{i}][orderable]"] = "true"
        p[f"columns[{i}][search][value]"] = ""
        p[f"columns[{i}][search][regex]"] = "false"
    return p


def retry_after_secs(r):
    """Return the Retry-After header as seconds, or None if absent/not numeric."""
    try:
        return max(0, int(r.headers.get("Retry-After", "")))
    except ValueError:
        return None


def fetch_top(limit, base_delay=BASE_DELAY):
    """Page through the screener sorted by Sharpe desc until we have >= limit rows.

    Pacing is adaptive: every 429 doubles the delay between requests (capped
    at MAX_DELAY) for the rest of the run, and a summary is printed at the end.
    """
    sess = open_session()
    rows = []
    start = 0
    draw = 1
    consec_429 = 0
    total_429 = 0
    delay = base_delay

    while len(rows) < limit:
        payload = make_payload(start, draw, SHARPE_COL_IDX, "desc")
        try:
            r = sess.post(BASE, data=payload, timeout=60,
                          headers={"X-Requested-With": "XMLHttpRequest"})
        except requests.RequestException as e:
            print(f"[req error] {e!r}; sleep 30s", flush=True)
            time.sleep(30)
            continue

        if r.status_code == 429:
            consec_429 += 1
            total_429 += 1
            delay = min(delay * 2, MAX_DELAY)
            wait = retry_after_secs(r)
            if wait is None:
                wait = min(60 + 30 * consec_429, 300)
            print(f"[429] consecutive={consec_429}, wait {wait}s; "
                  f"pacing raised to {delay:g}s", flush=True)
            time.sleep(wait)
            if consec_429 >= MAX_429_BEFORE_REOPEN:
                print("[refresh session]", flush=True)
                sess = open_session()
                consec_429 = 0
            continue
        if r.status_code != 200:
            print(f"[HTTP {r.status_code}] sleep 15s; body={r.text[:200]}", flush=True)
            time.sleep(15)
            continue
        consec_429 = 0

        batch = r.json().get("data", [])
        if not batch:
            print("[empty page] stopping early (no more rows)", flush=True)
            break
        rows.extend(batch)
        print(f"start={start} got={len(batch)} cum={len(rows)}/{limit}", flush=True)
        start += len(batch)
        draw += 1
        if len(rows) < limit:
            time.sleep(delay)

    if total_429:
        print(f"\n[rate-limited] hit HTTP 429 {total_429}x; pacing went "
              f"{base_delay:g}s -> {delay:g}s. Consider --delay {delay:g} next time.",
              flush=True)
    return rows


# ---------- output ----------

def write_csv(rows, path):
    """Write fetched rows to CSV. All risk metrics (Sharpe/Sortino/Volatility)
    are 3-year values from PV."""
    fieldnames = [
        "Ticker", "Name", "AssetClass", "Category",
        "Sharpe", "Sortino", "Volatility_pct",
        "Return_YTD_pct", "Return_1Y_pct", "Return_3Y_pct", "Return_5Y_pct",
        "YieldTTM_pct", "ExpenseRatio_pct", "Assets_USD", "Inception",
    ]

    def fmt(v, prec):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return ""
        return f"{v:.{prec}f}"

    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for raw in rows:
            rec = dict(zip(COLUMNS, raw))
            assets = parse_assets(rec["Assets"])
            w.writerow({
                "Ticker": strip_link(rec["Ticker"]),
                "Name": strip_link(rec["Name"]),
                "AssetClass": rec["AssetClass"],
                "Category": rec["Category"],
                "Sharpe": fmt(parse_num(rec["Sharpe"]), 3),
                "Sortino": fmt(parse_num(rec["Sortino"]), 3),
                "Volatility_pct": fmt(parse_pct(rec["Volatility"]), 2),
                "Return_YTD_pct": fmt(parse_pct(rec["YTD"]), 2),
                "Return_1Y_pct": fmt(parse_pct(rec["Return_1Y"]), 2),
                "Return_3Y_pct": fmt(parse_pct(rec["Return_3Y"]), 2),
                "Return_5Y_pct": fmt(parse_pct(rec["Return_5Y"]), 2),
                "YieldTTM_pct": fmt(parse_pct(rec["YieldTTM"]), 2),
                "ExpenseRatio_pct": fmt(parse_pct(rec["ExpenseRatio"]), 2),
                "Assets_USD": "" if math.isnan(assets) else f"{assets:.0f}",
                "Inception": rec["Inception"],
            })


# ---------- CLI ----------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Fetch the top US ETFs by 3-year Sharpe ratio from Portfolio Visualizer.",
        epilog=(
            "Examples:\n"
            "  %(prog)s                   # default: top 300 -> top_etfs.csv\n"
            "  %(prog)s -l 500            # top 500\n"
            "  %(prog)s -o my.csv\n"
            "  %(prog)s -d 5              # slower pacing if rate-limited\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-o", "--output",
        default="top_etfs.csv",
        help="Output CSV path (default: top_etfs.csv)",
    )
    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=300,
        help=(
            "Target row count (default: 300). "
            "Server returns 15 rows/page, so the actual count may overshoot; "
            "all fetched rows are kept."
        ),
    )
    parser.add_argument(
        "-d", "--delay",
        type=float,
        default=BASE_DELAY,
        help=(
            f"Seconds between requests (default: {BASE_DELAY:g}). "
            "Doubled automatically on each HTTP 429."
        ),
    )
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be >= 1")
    if args.delay < 0:
        parser.error("--delay must be >= 0")
    return args


def main(argv=None):
    args = parse_args(argv)
    print(
        f"Fetching top US ETFs by 3Y Sharpe (target: {args.limit} rows) -> {args.output}",
        flush=True,
    )

    raw = fetch_top(args.limit, args.delay)
    write_csv(raw, args.output)
    print(f"\n[saved] {len(raw)} rows -> {args.output}")


if __name__ == "__main__":
    sys.exit(main())
