#!/usr/bin/env python3
"""
woot_gpu_scraper.py

Checks Woot's official API for NVIDIA GPU deals (a la r/buildapcsales / u/ByteSizedDeals
style deal posts) and prints/logs any new matches.

Woot has a real developer API — no HTML scraping required:
  https://developer.woot.com

You need a free API key:
  1. Go to https://forums.woot.com/t/request-developer-api-key/734283
  2. Post in that thread asking for a key (don't post your email publicly, they'll DM it)
  3. Set it as an env var:  export WOOT_API_KEY="your-key-here"

USAGE
-----
  # one-off check, print results to terminal
  python3 woot_gpu_scraper.py

  # only show NEW deals since last run (dedup state saved to seen_offers.json)
  python3 woot_gpu_scraper.py --new-only

  # loop forever, checking every 15 minutes, only alerting on new deals
  python3 woot_gpu_scraper.py --new-only --loop --interval 900

  # open each NEW deal in a browser tab automatically (default behavior with --new-only)
  python3 woot_gpu_scraper.py --new-only --loop --interval 900

  # cap how many tabs it'll pop open in one go, and disable it entirely if you want
  python3 woot_gpu_scraper.py --new-only --max-tabs 3
  python3 woot_gpu_scraper.py --new-only --no-browser

  # widen or narrow what counts as a "GPU deal"
  python3 woot_gpu_scraper.py --keywords rtx,geforce,radeon --min-discount 10
"""

import argparse
import json
import os
import re
import sys
import time
import webbrowser
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

WOOT_API_BASE = "https://developer.woot.com"

# Feeds worth checking for GPUs. "Electronics" and "Computers" are where cards show up;
# "Featured" and "Wootoff" catch flash/blowout events (like a mini "Woot-Off").
DEFAULT_FEEDS = ["Computers", "Electronics", "Featured", "Wootoff"]

# Keywords used to decide "is this an NVIDIA GPU deal". Kept broad on purpose —
# better to over-match and filter visually than miss a weirdly-titled listing.
DEFAULT_KEYWORDS = [
    "nvidia", "geforce", "rtx", "gtx", "founders edition",
    "rtx 50", "rtx 40", "rtx 30",  # generation catch-alls
]

STATE_FILE = Path(__file__).parent / "seen_offers.json"


def fetch_feed(feedname: str, api_key: str) -> list:
    """Hit GET /feed/{feedname} and return the list of FeedItem dicts."""
    url = f"{WOOT_API_BASE}/feed/{feedname}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "x-api-key": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  [!] {feedname}: HTTP {e.code} — {e.reason}", file=sys.stderr)
        return []
    except urllib.error.URLError as e:
        print(f"  [!] {feedname}: network error — {e.reason}", file=sys.stderr)
        return []

    # GetNamedFeed returns {"Items": [...], "MarketingName": ..., "TotalPages": ...}
    return data.get("Items", [])


def is_gpu_deal(item: dict, keywords: list) -> bool:
    haystack = " ".join(
        str(item.get(k, "") or "") for k in ("Title", "Subtitle")
    ).lower()
    return any(kw.lower() in haystack for kw in keywords)


def price_and_discount(item: dict):
    """Woot prices are ranges (Minimum/Maximum). Use Minimum as the headline price."""
    sale = item.get("SalePrice") or {}
    list_ = item.get("ListPrice") or {}
    sale_min = sale.get("Minimum")
    list_min = list_.get("Minimum")

    discount_pct = None
    if sale_min is not None and list_min not in (None, 0):
        discount_pct = round((1 - (sale_min / list_min)) * 100)

    return sale_min, list_min, discount_pct


def format_deal(item: dict) -> str:
    sale_min, list_min, discount_pct = price_and_discount(item)

    price_str = f"${sale_min:,.2f}" if sale_min is not None else "price N/A"
    if list_min and discount_pct is not None:
        price_str += f"  (list ${list_min:,.2f}, {discount_pct}% off)"

    flags = []
    if item.get("IsWootOff"):
        flags.append("WOOT-OFF")
    if item.get("IsFeatured"):
        flags.append("FEATURED")
    if item.get("IsSoldOut"):
        flags.append("SOLD OUT")
    flag_str = f" [{', '.join(flags)}]" if flags else ""

    title = item.get("Title", "Untitled offer")
    url = item.get("Url", "")

    return f"• {title}{flag_str}\n  {price_str}\n  {url}"


def load_seen() -> set:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_seen(seen: set):
    STATE_FILE.write_text(json.dumps(sorted(seen)))


def open_deals_in_browser(deals: list, max_tabs: int = 5, tab_delay: float = 1.0):
    """Open each deal's URL in a new tab of the OS default browser (e.g. Chrome).

    Note: this opens tabs on the machine actually running the script, so it only
    makes sense run locally / on your own desktop, not on a remote server.
    """
    to_open = deals[:max_tabs]
    skipped = len(deals) - len(to_open)

    for item in to_open:
        url = item.get("Url")
        if not url:
            continue
        print(f"  -> opening tab: {item.get('Title', url)}")
        webbrowser.open_new_tab(url)
        time.sleep(tab_delay)  # small gap so the browser/OS doesn't choke on a burst

    if skipped > 0:
        print(f"  ({skipped} more new deal(s) found but not opened — raise --max-tabs to see them)")


def post_to_discord(webhook_url: str, deals: list):
    lines = [format_deal(d).replace("\n  ", " — ") for d in deals]
    content = "**🎮 New NVIDIA GPU deals on Woot!**\n" + "\n".join(lines)
    # Discord has a 2000 char message limit; trim if needed.
    if len(content) > 1900:
        content = content[:1900] + "\n…(truncated)"
    payload = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        print(f"  [!] Discord webhook failed: {e}", file=sys.stderr)


def run_once(args, api_key: str) -> int:
    is_first_run = args.new_only and not STATE_FILE.exists()
    seen = load_seen() if args.new_only else set()
    all_matches = []

    for feed in args.feeds:
        items = fetch_feed(feed, api_key)
        for item in items:
            if not is_gpu_deal(item, args.keywords):
                continue
            _, _, discount_pct = price_and_discount(item)
            if args.min_discount and (discount_pct is None or discount_pct < args.min_discount):
                continue
            all_matches.append(item)

    # De-dup across feeds by OfferId (a deal can appear in multiple feeds)
    by_id = {item.get("OfferId"): item for item in all_matches}
    all_matches = list(by_id.values())

    new_matches = [m for m in all_matches if m.get("OfferId") not in seen]

    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    to_show = new_matches if args.new_only else all_matches

    if to_show:
        print(f"\n[{ts}] {len(to_show)} GPU deal(s){' (new)' if args.new_only else ''}:\n")
        for item in to_show:
            print(format_deal(item))
            print()
    else:
        print(f"[{ts}] No {'new ' if args.new_only else ''}NVIDIA GPU deals found.")

    if is_first_run and new_matches:
        # Don't blast open a tab for every deal already live the first time this runs —
        # just record today's deals as the baseline. Only genuinely *new* deals from
        # here on will open tabs.
        print(f"  (first run — seeding baseline of {len(new_matches)} existing deal(s), no tabs opened)")
    elif args.open_browser and new_matches:
        open_deals_in_browser(new_matches, max_tabs=args.max_tabs, tab_delay=args.tab_delay)

    if args.discord_webhook and new_matches and not is_first_run:
        post_to_discord(args.discord_webhook, new_matches)

    if args.new_only:
        seen.update(item.get("OfferId") for item in all_matches if item.get("OfferId"))
        save_seen(seen)

    return len(to_show)


def parse_args():
    p = argparse.ArgumentParser(description="Check Woot for NVIDIA GPU deals.")
    p.add_argument("--feeds", default=",".join(DEFAULT_FEEDS),
                    help=f"Comma-separated Woot feed names (default: {','.join(DEFAULT_FEEDS)}). "
                         "Options: All, Clearance, Computers, Electronics, Featured, Home, "
                         "Gourmet, Shirts, Sports, Tools, Wootoff")
    p.add_argument("--keywords", default=",".join(DEFAULT_KEYWORDS),
                    help="Comma-separated title keywords that count as a GPU match")
    p.add_argument("--min-discount", type=int, default=0,
                    help="Only show deals with at least this %% off list price")
    p.add_argument("--new-only", action="store_true",
                    help="Only show/alert deals not seen on a previous run (persisted to seen_offers.json)")
    p.add_argument("--loop", action="store_true", help="Run continuously")
    p.add_argument("--interval", type=int, default=900,
                    help="Seconds between checks when --loop is set (default 900 = 15 min)")
    p.add_argument("--open-browser", dest="open_browser", action="store_true", default=True,
                    help="Open each new deal in a browser tab (default: on)")
    p.add_argument("--no-browser", dest="open_browser", action="store_false",
                    help="Disable auto-opening browser tabs for new deals")
    p.add_argument("--max-tabs", type=int, default=5,
                    help="Max number of tabs to pop open in a single check (default 5)")
    p.add_argument("--tab-delay", type=float, default=1.0,
                    help="Seconds to wait between opening each tab (default 1.0)")
    p.add_argument("--discord-webhook", default=os.environ.get("DISCORD_WEBHOOK_URL"),
                    help="(optional) also post new deals to a Discord webhook URL")
    args = p.parse_args()

    args.feeds = [f.strip() for f in args.feeds.split(",") if f.strip()]
    args.keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    return args


def main():
    api_key = os.environ.get("WOOT_API_KEY")
    if not api_key:
        print(
            "ERROR: No API key found.\n"
            "Set the WOOT_API_KEY environment variable.\n"
            "Get a free key by posting in: https://forums.woot.com/t/request-developer-api-key/734283\n",
            file=sys.stderr,
        )
        sys.exit(1)

    args = parse_args()

    if args.loop:
        print(f"Watching feeds {args.feeds} every {args.interval}s. Ctrl+C to stop.")
        try:
            while True:
                run_once(args, api_key)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        run_once(args, api_key)


if __name__ == "__main__":
    main()
