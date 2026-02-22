# LoL RIOT ItemSet ID Fixer (SR 5v5)

Small Windows tool to patch League of Legends **recommended item sets** so the in-game casual UI shows full lists.

It scans your `Champions/*/Recommended/*.json` item sets and, **for Summoner's Rift (SR 5v5) only**, replaces selected item IDs (e.g. `3075`) with their SR-variant IDs (e.g. `323075`).

## Why

Some custom recommended item sets may not show all items during casual games on Summoner's Rift.
This tool rewrites specific item IDs inside Riot item set JSON files to their SR-variant IDs, which helps the full list show reliably.

## What it does

- Detects champions by folder name inside `.../League of Legends/Config/Champions`
- Reads `*/Recommended/*.json`
- Only processes files where `"map": "SR"`
- Replaces IDs using an **embedded mapping** (single-file tool)
- Shows a report per champion and per item (Spanish + English names)
- Creates a `.bak` backup next to any modified JSON (unless disabled)

## How to use (recommended: EXE)

1) Download the latest Windows EXE from **GitHub Releases**.
2) Run the EXE (GUI opens).
3) Make sure it points to your `.../League of Legends/Config/Champions` folder.
4) Keep **Apply changes** enabled (and backups ON).
5) Click **Run**.

The table shows champions detected for SR and what items were changed (Spanish + English).

## Run (Python)

Double-click / run without args to open the GUI:

- `python update_riot_itemset_ids.py`

CLI usage:

- Dry-run (no writes):
  - `python update_riot_itemset_ids.py --dry-run`
- Apply changes:
  - `python update_riot_itemset_ids.py`
- If auto-detection fails:
  - `python update_riot_itemset_ids.py --root "C:/Riot Games/League of Legends/Config/Champions"`

## Screenshots

Add your images under [assets/](assets/) and reference them here.

- Main window: `assets/gui-main.png`
  - Example markdown: `![GUI main](assets/gui-main.png)`
- Results table: `assets/gui-results.png`
  - Example markdown: `![Results](assets/gui-results.png)`

Tip: use `Win + Shift + S` to capture.

## Demo video

Recommended options:

- GIF: export to `assets/demo.gif` and embed it:
  - `![Demo](assets/demo.gif)`
- MP4: upload `demo.mp4` to the Release assets and link it from here.

## Build a standalone EXE (no Python required for users)

On the machine that will build the EXE:

1) Install Python 3.10+ (only needed for building)
2) Install PyInstaller:

- `pip install pyinstaller`

3) Build a GUI EXE (recommended):

- `pyinstaller --onefile --noconsole update_riot_itemset_ids.py`

The executable will be created under `dist/update_riot_itemset_ids.exe`.

Optional: build a console EXE (shows terminal output):

- `pyinstaller --onefile --console update_riot_itemset_ids.py`

## Safety

- The tool writes JSON files under your League config folder.
- Backups: when applying changes, it creates `*.json.bak` files next to modified files.

## Notes

- The embedded mapping currently includes the items you provided in your CSV.
- If Riot changes IDs in future patches, the mapping may need updates.

## Release template

See [RELEASE_NOTES_v1.0.0.md](RELEASE_NOTES_v1.0.0.md) for a ready-to-paste first release description.
