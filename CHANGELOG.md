# Changelog

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
