# Changelog

## 0.2.5 — 2026-08-18

- Made existing logged meals and totals follow current food-library nutrition values.
- Preserved the complete meal form when previewing nutrition, including selected foods, servings, time and note.
- Added dated nutrition trends for every tracked measure, defaulting to the current week and linked from overview cards.
- Confirmed food additions and edits are committed to the add-on's local SQLite database.

## 0.2.4 — 2026-08-16

- Fixed every stylesheet, navigation, form and redirect URL when the app runs behind Home Assistant ingress.
- Reworked the remaining food, weight, settings, review and meal-planning screens into a consistent responsive interface.
- Removed the external font dependency, added local SVG icons and added an add-on health check.
- Added ingress regression coverage so root-path links cannot silently return.

## 0.2.2 — 2026-08-16

- Rebuilt the repository as the Mounjaro Coach Home Assistant ingress add-on.
- Added transactional SQLite meals, common foods, rollover days, weight history, settings, JSON transfer and conservative historical import.
- Added local responsive UI, nutrition/tolerance warnings and Home Assistant notification deduplication.
- Added multi-architecture container metadata and automated rule-focused tests.
