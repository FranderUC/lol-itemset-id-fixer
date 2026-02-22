# v1.0.0

First public release.

## Highlights

- Windows GUI (no args opens the app)
- Scans `Champions/*/Recommended/*.json` and only processes `map=SR` (Summoner's Rift 5v5)
- Replaces selected base item IDs (e.g. `3075`) with SR-variant IDs (e.g. `323075`)
- Shows detected champions and a per-champion item report (Spanish + English item names)
- Creates `*.json.bak` backups next to modified files (unless disabled)

## Download

- `update_riot_itemset_ids.exe` (standalone)

## Notes

- If Windows SmartScreen warns about an unsigned EXE, use "More info" → "Run anyway".
- If Riot changes item IDs in future patches, the embedded mapping may need an update.
