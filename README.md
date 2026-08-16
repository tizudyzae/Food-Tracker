# Mounjaro Coach

A private, mobile-first Home Assistant add-on for confirmed food, nutrition and weight tracking. It runs locally, uses SQLite, has no cloud or LLM dependency, and distinguishes planning from food actually eaten.

## Install in Home Assistant

1. In Home Assistant, open **Settings → Add-ons → Add-on Store**.
2. Open the three-dot menu, select **Repositories**, and add `https://github.com/tizudyzae/foodtracker`.
3. Refresh the store, select **Mounjaro Coach**, and choose **Install**.
4. Start it, optionally enable **Start on boot** and **Watchdog**, then choose **Open Web UI**.

The add-on supports 64-bit Intel/AMD and Raspberry Pi/ARM systems (`amd64` and `aarch64`). It is ingress-only and opens no host port.

## First run

Open **Settings** in the app and review the default 2,000–2,200 kcal range, 150–170 g protein guidance, Europe/London timezone, 04:00 rollover, warning levels and meal windows. Reminders are off by default. Use **Foods** to check seeded portions, then **Log meal**. “Calculate only” never persists a meal; only **Save as eaten** does.

Run **idempotent reference import** once from Settings to load only conservatively recoverable, explicitly confirmed meals. The review screen explains skipped/uncertain material. Re-running is safe.

## Notifications

Set a Home Assistant service such as `notify.mobile_app_your_phone`, set quiet hours, and explicitly enable reminders. The add-on calls the Home Assistant Core services API using the injected Supervisor token; it never logs or stores the token. Each reminder window has a durable deduplication key. The weekly reminder follows the comparable-conditions guidance: morning, after the toilet and before food/drink.

## Data, backups and transfer

SQLite data is stored at `/data/coach.db`, which Home Assistant includes in add-on backups. WAL mode and transactions protect concurrent writes. Settings → **Export JSON** creates a portable (sensitive) backup; **Import** validates JSON and replaces application tables transactionally. Keep exports private because they contain food and weight history.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r food_tracker/requirements.txt pytest
.venv/bin/pytest
DATA_DIR=/tmp/mounjaro-coach .venv/bin/flask --app food_tracker.app.web:create_app run
```

Build from the repository root with `docker build --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.21 food_tracker`.

## Known limitations

- Original nutrition photos in the chat exports are remote links, not repository assets. Only values supported by the rules and unambiguous text are seeded; ambiguous meals stay outside totals in Review.
- Common foods can be added and archived/restored. Existing seeded records are intentionally source-preserving; changed products should be archived and replaced with a newly sourced entry.
- The trend chart is intentionally simple and does not diagnose weight changes.
- Historical import is deliberately conservative: most photo-dependent entries remain in Review until manually resolved from labels.

Warnings provide useful tolerance context and are not medical advice or diagnoses.
