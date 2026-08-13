# Movie Confirmation

Poll **BookMyShow** and **District** on a schedule and send a **Telegram** alert the moment tickets you care about go live.

This is a lightweight rule engine, not a mobile app. You add watch rules in `rules.yaml`, host the checker for free on **GitHub Actions**, and get pinged when a target date becomes bookable.

## What it does

- Watches a movie at a specific cinema
- Targets an exact date (`target_date`) or a weekday (`target_weekday`, e.g. `saturday`)
- Checks District and/or BookMyShow
- Sends Telegram only on the transition from **not available → available**
- Remembers state in `state.json` so you are not spammed

## Quick start

### 1. Install locally

```bash
cd MovieConfirmaiton
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

### 2. Create a Telegram bot

1. Open Telegram and message `@BotFather`
2. Run `/newbot` and copy the bot token
3. Start a chat with your bot and send any message
4. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
5. Copy your `chat.id`

Put both values in `.env`:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Test it:

```bash
python main.py test-alert
```

### 3. Add a watch rule

Edit [`rules.yaml`](rules.yaml). Example already included:

```yaml
rules:
  - id: spiderman-moa-saturday
    enabled: true
    movie: "Spider-Man: Brand New Day"
    cinema:
      name: "INOX Megaplex Mall of Asia"
      district:
        cinema_id: "1025975"
        slug: "inox-megaplex-mall-of-asia-byatarayanapura-bengaluru-in-bengaluru-CD1025975"
      bookmyshow:
        region: "BANG"
        venue_code: "IMMO"
        slug: "inox-megaplex-mall-of-asia-bangalore"
    target_weekday: saturday
    platforms: [district, bookmyshow]
    links:
      district: "https://www.district.in/movies/inox-megaplex-mall-of-asia-byatarayanapura-bengaluru-in-bengaluru-CD1025975"
      bookmyshow: "https://in.bookmyshow.com/cinemas/bang/inox-megaplex-mall-of-asia-bangalore/buytickets/IMMO"
```

Run a check:

```bash
python main.py list-rules
python main.py check --dry-run
python main.py check
```

## Rule fields

| Field | Required | Description |
| --- | --- | --- |
| `id` | yes | Unique rule name |
| `enabled` | no | Default `true` |
| `movie` | yes | Movie title to match |
| `cinema.name` | yes | Human-readable cinema name |
| `cinema.district.cinema_id` | for District | Cinema ID from District URL/page |
| `cinema.district.slug` | for District | Cinema slug from District URL |
| `cinema.bookmyshow.region` | for BMS | e.g. `BANG`, `HYD`, `MUM` |
| `cinema.bookmyshow.venue_code` | for BMS | Venue code from BMS URL |
| `cinema.bookmyshow.slug` | for BMS | Cinema slug from BMS URL |
| `target_date` | one of | Exact date `YYYY-MM-DD` |
| `target_weekday` | one of | `monday` … `sunday` |
| `platforms` | no | `district`, `bookmyshow`, or both |
| `bookmyshow_event_code` | no | Optional BMS event code if page parsing fails |
| `watch_until` | no | Stop checking after this date |
| `links` | no | Booking links included in alerts |

### Targeting a weekday

If you set `target_weekday: saturday`, the bot watches the next Saturday that is not yet listed. When Saturday showtimes for your movie appear, you get alerted.

### Targeting a specific date

```yaml
target_date: "2026-08-20"
```

## Finding cinema IDs

### District

Open the cinema page on District, for example:

`https://www.district.in/movies/inox-megaplex-mall-of-asia-byatarayanapura-bengaluru-in-bengaluru-CD1025975`

- `cinema_id`: `1025975`
- `slug`: everything after `/movies/`

### BookMyShow

Open the cinema booking page, for example:

`https://in.bookmyshow.com/cinemas/bang/inox-megaplex-mall-of-asia-bangalore/buytickets/IMMO/20260815`

- `region`: `bang` → use uppercase `BANG` in rules
- `slug`: `inox-megaplex-mall-of-asia-bangalore`
- `venue_code`: `IMMO`

## Free hosting on GitHub Actions

1. Push this folder to a GitHub repository
2. Add repository secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. Enable GitHub Actions
4. The workflow in [`.github/workflows/check.yml`](.github/workflows/check.yml) runs every 10 minutes

GitHub Actions is free for public repos and includes enough minutes for this use case. Scheduled runs can be delayed by a few minutes, but it is still much faster than manual checking.

### Manual run

In GitHub: **Actions → Ticket Availability Check → Run workflow**

## Commands

```bash
python main.py list-rules
python main.py check
python main.py check --dry-run
python main.py test-alert
```

## Notes

- District is parsed from embedded page data and is generally reliable.
- BookMyShow may block some datacenter IPs. GitHub Actions usually works; if not, add `bookmyshow_event_code` to the rule or rely on District alerts (both platforms share the same cinema inventory).
- This tool only detects availability. It does not book tickets for you.
- First run baseline: if tickets are already available when you add a rule, it records state without alerting so you do not get a false alarm.

## Example: watch The Odyssey next time

```yaml
- id: odyssey-pvr-next
  enabled: true
  movie: "The Odyssey"
  cinema:
    name: "PVR Nexus Koramangala"
    district:
      cinema_id: "YOUR_ID"
      slug: "your-district-slug"
    bookmyshow:
      region: "BANG"
      venue_code: "YOUR_CODE"
      slug: "your-bms-slug"
  target_date: "2026-09-12"
  platforms: [district, bookmyshow]
```

Disable or delete old rules by setting `enabled: false` or removing them from `rules.yaml`.
