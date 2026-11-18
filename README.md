# Movie Confirmation

Watches **District** cinema pages and sends a **Telegram + email** alert the moment a movie is listed at a specific cinema.

Currently watching (see [`rules.yaml`](rules.yaml)):

| Movie | Cinema | Show date watched |
| --- | --- | --- |
| Avengers: Doomsday | INOX Megaplex Mall of Asia | Sun 20 Dec 2026 |
| Dune: Part Three | INOX Megaplex Mall of Asia | Sun 20 Dec 2026 |
| Godzilla Minus Zero | PVR Aura Park Square, Whitefield | Fri 20 Nov 2026 |

A rule with `target_date` alerts only when shows appear on that exact date. Shows on other dates are ignored.

## How it works

1. Fetches the cinema's District page, which includes the list of bookable dates (`sessionDates`).
2. For each bookable date, fetches `?fromdate=YYYY-MM-DD` and looks for the movie in that day's sessions.
3. The first time the movie appears at that cinema, it sends **BOOKING OPEN** with showtimes, screen format, seats left and a booking link. Later, when more dates are added, it sends **New dates added**.
4. Each date is alerted once (tracked in `state.json`). If sending fails, it retries on the next run.
5. If District can't be reached for 6 runs in a row, it sends one **watcher can't reach District** alert so silence never means "broken".

Only the showtime list is checked, not the page text. District pages mention upcoming movies in footers, and those mentions do not trigger alerts. `match` phrases stop look-alikes, so "Dune: Part Two" re-releases and "Godzilla x Kong" are not matched.

District serves this data to plain HTTP requests, so no browser/Playwright is needed. BookMyShow returns HTTP 403 to scripts, so these rules don't use it. Both sites sell the same cinema inventory.

## Setup (10 minutes)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

### Telegram

1. Message `@BotFather` → `/newbot` → copy the token
2. Send any message to your new bot
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`

### Gmail

1. Turn on 2-Step Verification on your Google account
2. Create an App Password at https://myaccount.google.com/apppasswords
3. Put it in `EMAIL_APP_PASSWORD` (spaces are fine)

Fill in `.env`, then:

```bash
python main.py test-alert       # should arrive on Telegram and email
python main.py check --dry-run  # prints what it would send, sends nothing
```

## Running it

### On your PC (fastest, works now)

```bash
python main.py watch            # checks every 5 minutes; keep the window open
```

### Free on GitHub Actions (runs when your PC is off)

1. Push this repo to GitHub as a **public** repo (unlimited free minutes; secrets stay hidden)
2. Settings → Secrets and variables → Actions → add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `EMAIL_USER`, `EMAIL_APP_PASSWORD`, `EMAIL_TO`
3. Actions → Ticket Availability Check → **Run workflow** once and check the log says `Errors:` is absent

It is scheduled every 5 minutes, but GitHub often starts runs 5–15 minutes late. If you run both the PC watcher and GitHub, you may get each alert twice, because they keep separate state.

## Adding a movie

```yaml
- id: some-movie-some-cinema
  movie: "Movie Title"
  match: ["movie title"]          # whole-word phrases matched against District's title
  cinema:
    name: "Cinema name for alerts"
    district:
      cinema_id: "1022308"        # the number after CD in the URL
      slug: "pvr-aura-park-square-whitefield-bengaluru-CD1022308"
  from_date: "2026-11-18"         # ignore listings before this
  watch_until: "2026-12-10"       # stop checking after this
  platforms: [district]
  links:
    district: "https://www.district.in/movies/pvr-aura-park-square-whitefield-bengaluru-CD1022308"
```

Find the cinema on District (e.g. via `district.in/movies/cinemas-in-bengaluru`) and copy the slug from its URL.

Rules can also use `target_date: "2026-08-20"` or `target_weekday: saturday` to watch one specific date, optionally with `bookmyshow` too.

## Commands

```bash
python main.py list-rules
python main.py check [--dry-run]
python main.py watch [--interval 300]
python main.py test-alert
```

This tool only detects availability. It does not book tickets.
