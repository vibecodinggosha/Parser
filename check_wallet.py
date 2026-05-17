#!/usr/bin/env python3
"""
TON wallet transaction checker for a specific date.

Usage:
    python3 check_wallet.py

Requirements:
    pip install requests  (optional - falls back to urllib if not installed)
"""

import json
import sys
import time
from datetime import datetime, timezone

try:
    import requests
    def http_get(url):
        r = requests.get(url, timeout=20, headers={"Accept": "application/json"})
        r.raise_for_status()
        return r.json()
except ImportError:
    import urllib.request
    def http_get(url):
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

WALLET     = "EQCGehWjAX0q1Kk8nxHErhYypbWprhUSs3287DUecfVont4H"
TARGET_DATE = "2025-12-10"

# 2025-12-10 UTC boundaries (inclusive)
DATE_START = 1765324800   # 00:00:00 UTC
DATE_END   = 1765411199   # 23:59:59 UTC

NANO = 1_000_000_000


def fmt_ton(nano):
    val = int(nano) / NANO
    if val == 0:
        return "0 TON"
    return f"{val:.4f} TON"


def ts_utc(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ── TonCenter v2 ─────────────────────────────────────────────────────────────

def fetch_toncenter(api_key=None):
    """
    Paginates through TonCenter v2 getTransactions.
    Free tier: ~1 req/s without a key. Get a free key at https://toncenter.com/
    """
    collected = []
    last_lt = None
    last_hash = None

    while True:
        url = (
            f"https://toncenter.com/api/v2/getTransactions"
            f"?address={WALLET}&limit=100&archival=true"
        )
        if api_key:
            url += f"&api_key={api_key}"
        if last_lt and last_hash:
            url += f"&lt={last_lt}&hash={last_hash}&to_lt=0"

        try:
            data = http_get(url)
        except Exception as e:
            print(f"  [TonCenter] {e}", file=sys.stderr)
            return None

        if not data.get("ok"):
            print(f"  [TonCenter] API error: {data.get('error')}", file=sys.stderr)
            return None

        batch = data.get("result", [])
        if not batch:
            break

        for tx in batch:
            utime = int(tx.get("utime", 0))
            if utime < DATE_START:
                return collected
            if utime <= DATE_END:
                collected.append(tx)

        last = batch[-1]
        last_lt   = last["transaction_id"]["lt"]
        last_hash = last["transaction_id"]["hash"]

        if len(batch) < 100:
            break

        time.sleep(1)  # free-tier rate limit

    return collected


# ── TONAPI v2 ─────────────────────────────────────────────────────────────────

def fetch_tonapi(api_key=None):
    """
    Uses TONAPI (tonapi.io) which supports after_lt / before_lt filtering.
    Free API key at https://tonconsole.com/
    """
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    before_lt = DATE_END * 10**6     # approximate upper bound in microseconds
    collected = []

    try:
        import requests as req_lib
        has_requests = True
    except ImportError:
        has_requests = False

    cursor = None

    while True:
        url = (
            f"https://tonapi.io/v2/blockchain/accounts/{WALLET}/transactions"
            f"?limit=100"
        )
        if cursor:
            url += f"&before_lt={cursor}"

        try:
            if has_requests:
                import requests as rq
                r = rq.get(url, headers=headers, timeout=20)
                r.raise_for_status()
                data = r.json()
            else:
                import urllib.request as ul
                req = ul.Request(url, headers=headers)
                with ul.urlopen(req, timeout=20) as r:
                    data = json.loads(r.read())
        except Exception as e:
            print(f"  [TONAPI] {e}", file=sys.stderr)
            return None

        txs = data.get("transactions", [])
        if not txs:
            break

        for tx in txs:
            utime = int(tx.get("utime", 0))
            if utime < DATE_START:
                return collected
            if utime <= DATE_END:
                collected.append(tx)

        cursor = txs[-1].get("lt")
        if not cursor or len(txs) < 100:
            break

    return collected


# ── Formatters ────────────────────────────────────────────────────────────────

def print_toncenter_tx(tx):
    utime = int(tx.get("utime", 0))
    tid   = tx.get("transaction_id", {})
    print(f"\n{'─'*72}")
    print(f"  Time  : {ts_utc(utime)}")
    print(f"  LT    : {tid.get('lt', '?')}")
    print(f"  Hash  : {tid.get('hash', '?')}")
    print(f"  Fee   : {fmt_ton(tx.get('fee', 0))}")

    in_msg = tx.get("in_msg")
    if in_msg:
        src   = in_msg.get("source") or "external"
        val   = in_msg.get("value", 0)
        body  = in_msg.get("message") or ""
        print(f"  IN    : from {src}  value={fmt_ton(val)}")
        if body:
            print(f"          comment: {body}")

    for msg in tx.get("out_msgs", []):
        dst  = msg.get("destination") or "—"
        val  = msg.get("value", 0)
        body = msg.get("message") or ""
        print(f"  OUT   : to   {dst}  value={fmt_ton(val)}")
        if body:
            print(f"          comment: {body}")


def print_tonapi_tx(tx):
    utime = int(tx.get("utime", 0))
    print(f"\n{'─'*72}")
    print(f"  Time  : {ts_utc(utime)}")
    print(f"  Hash  : {tx.get('hash', '?')}")
    print(f"  LT    : {tx.get('lt', '?')}")

    total_fee = tx.get("total_fees", 0)
    print(f"  Fee   : {fmt_ton(total_fee)}")

    in_msg = tx.get("in_msg")
    if in_msg:
        src = in_msg.get("source", {})
        src_addr = src.get("address", "external") if isinstance(src, dict) else str(src)
        val  = in_msg.get("value", 0)
        body = (in_msg.get("decoded_body") or {}).get("text") or in_msg.get("raw_body", "")
        print(f"  IN    : from {src_addr}  value={fmt_ton(val)}")
        if body:
            print(f"          comment: {body}")

    for msg in tx.get("out_msgs", []):
        dst = msg.get("destination", {})
        dst_addr = dst.get("address", "—") if isinstance(dst, dict) else str(dst)
        val  = msg.get("value", 0)
        body = (msg.get("decoded_body") or {}).get("text") or ""
        print(f"  OUT   : to   {dst_addr}  value={fmt_ton(val)}")
        if body:
            print(f"          comment: {body}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"{'═'*72}")
    print(f"  Wallet : {WALLET}")
    print(f"  Date   : {TARGET_DATE} (UTC)")
    print(f"  Range  : {ts_utc(DATE_START)} → {ts_utc(DATE_END)}")
    print(f"{'═'*72}")

    # Try TonCenter first
    print("\n[1/2] Trying TonCenter API...")
    txs = fetch_toncenter()

    if txs is not None:
        if not txs:
            print(f"\nNo transactions on {TARGET_DATE}.")
        else:
            print(f"\nFound {len(txs)} transaction(s):")
            for tx in txs:
                print_toncenter_tx(tx)
            print(f"\n{'═'*72}")
            print(f"Total: {len(txs)} transaction(s) on {TARGET_DATE}")
        return

    # Fallback: TONAPI
    print("\n[2/2] Trying TONAPI...")
    txs = fetch_tonapi()

    if txs is not None:
        if not txs:
            print(f"\nNo transactions on {TARGET_DATE}.")
        else:
            print(f"\nFound {len(txs)} transaction(s):")
            for tx in txs:
                print_tonapi_tx(tx)
            print(f"\n{'═'*72}")
            print(f"Total: {len(txs)} transaction(s) on {TARGET_DATE}")
        return

    print("\nBoth APIs failed. Possible reasons:")
    print("  - Rate limited (try again in a minute)")
    print("  - Get a free API key at https://toncenter.com/ or https://tonconsole.com/")
    print("  - Then pass it to fetch_toncenter(api_key='YOUR_KEY')")


if __name__ == "__main__":
    main()
