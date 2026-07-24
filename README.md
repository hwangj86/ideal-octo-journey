# Woot NVIDIA GPU Deal Scraper

Checks Woot's **official developer API** (not HTML scraping) for NVIDIA GPU listings and
prints them out buildapcsales-style: title, price, % off list, link. Can loop on an
interval and only alert on *new* deals, optionally posting to a Discord webhook.

## 1. Get a free Woot API key

Woot doesn't self-serve keys — you request one on their forum and they DM it to you:

1. Go to https://forums.woot.com/t/request-developer-api-key/734283
2. Reply in that thread asking for a key (don't post your email in the thread — they'll
   message you)
3. Keys are generated weekly, so it may take a few days

Rate limits: 1 req/sec, burst of 10, 1000 requests/day — plenty for polling every 15 min.

## 2. Set your key

```bash
export WOOT_API_KEY="the-key-they-sent-you"
```

## 3. Run it

```bash
# one-off check
python3 woot_gpu_scraper.py

# only show deals you haven't seen before (tracked in seen_offers.json)
python3 woot_gpu_scraper.py --new-only

# run forever, checking every 15 min — any NEW deal automatically opens
# in a new tab in your default browser (e.g. Chrome)
python3 woot_gpu_scraper.py --new-only --loop --interval 900
```

### About the auto-opening browser tabs

- On by default whenever `--new-only` finds a deal it hasn't seen before.
- **First run is special:** since there's no history yet, every currently-live GPU deal
  would technically be "new." Instead of popping open 15 tabs on your first run, the
  script just records the current deals as its baseline. From the *second* run onward,
  only genuinely new deals open tabs.
- Capped at 5 tabs per check by default so a big Woot-Off doesn't nuke your browser —
  adjust with `--max-tabs`.
- Turn it off entirely with `--no-browser` (useful if you just want the terminal output,
  or if you're running this on a headless/remote machine where there's no browser to open).

```bash
# only pop open at most 2 tabs per check, 2 sec apart
python3 woot_gpu_scraper.py --new-only --loop --max-tabs 2 --tab-delay 2

# disable tab-opening, just print to terminal
python3 woot_gpu_scraper.py --new-only --no-browser

# (optional) also push new deals to a Discord channel, in addition to opening tabs
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
python3 woot_gpu_scraper.py --new-only --loop --discord-webhook "$DISCORD_WEBHOOK_URL"
```

**Note:** the browser-tab feature opens tabs on whatever machine actually runs the
script — so run it on your desktop/laptop directly (not on a remote server), since
`webbrowser.open_new_tab()` controls the local OS's default browser.

## Customizing what counts as a "GPU deal"

By default it matches titles containing: `nvidia, geforce, rtx, gtx, founders edition,
rtx 50, rtx 40, rtx 30`. Override with:

```bash
python3 woot_gpu_scraper.py --keywords rtx,geforce,radeon,rx
```

Only want deals with a real discount?

```bash
python3 woot_gpu_scraper.py --min-discount 15
```

## Running it unattended (optional)

**Cron** (check every 15 min, log to file):
```
*/15 * * * * WOOT_API_KEY=xxx /usr/bin/python3 /path/to/woot_gpu_scraper.py --new-only >> /path/to/woot_gpu.log 2>&1
```

**Or just leave `--loop` running** in a `screen`/`tmux` session or as a systemd service.

## How it differs from a browser-scraper approach

Woot exposes `GET /feed/{feedname}` (Computers, Electronics, Featured, Wootoff, etc.) which
returns live offers with price, title, category, and URL — this is the same data source
deal-alert bots like r/buildapcsales' AutoModerator-style tools and Reddit deal accounts
ultimately rely on for Woot listings, just accessed the sanctioned way instead of parsing
HTML (which breaks whenever Woot changes their frontend, and against their ToS to scrape).
