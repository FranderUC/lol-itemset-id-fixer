from __future__ import annotations

import argparse
import json
import os
import shutil
import string
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    TK_AVAILABLE = True
except Exception:
    TK_AVAILABLE = False


@dataclass(frozen=True)
class ItemInfo:
    old_id: str
    new_id: str
    name_es: str
    name_en: str


# Embedded mapping (single-file, repo-friendly): code1 -> (code2, ES name, EN name)
# Source: your CSV "Objetos LOL.csv". Keep only what is needed for replacement + reporting.
EMBEDDED_ITEM_MAP: Dict[str, ItemInfo] = {
    "2065": ItemInfo("2065", "322065", "Canción de batalla de Shurelya", "Shurelya's Battlesong"),
    "3002": ItemInfo("3002", "323002", "Marcasendas", "Trailblazer"),
    "3003": ItemInfo("3003", "323003", "Bastón del arcángel", "Archangel's Staff"),
    "3004": ItemInfo("3004", "323004", "Manamune", "Manamune"),
    "3050": ItemInfo("3050", "323050", "Convergencia de Zeke", "Zeke's Convergence"),
    "3075": ItemInfo("3075", "323075", "Malla de espinas", "Thornmail"),
    "3107": ItemInfo("3107", "323107", "Redención", "Redemption"),
    "3109": ItemInfo("3109", "323109", "Promesa de caballero", "Knight's Vow"),
    "3110": ItemInfo("3110", "323110", "Corazón de hielo", "Frozen Heart"),
    "3119": ItemInfo("3119", "323119", "Llegada del invierno", "Winter's Approach"),
    "3190": ItemInfo("3190", "323190", "Medallón de los Solari de Hierro", "Locket of the Iron Solari"),
    "3222": ItemInfo("3222", "323222", "Bendición de Mikael", "Mikael's Blessing"),
    "3504": ItemInfo("3504", "323504", "Incensario ardiente", "Ardent Censer"),
    "4005": ItemInfo("4005", "324005", "Mandato imperial", "Imperial Mandate"),
    "6616": ItemInfo("6616", "326616", "Bastón de aguas fluidas", "Staff of Flowing Water"),
    "6617": ItemInfo("6617", "326617", "Renovación de piedra lunar", "Moonstone Renewer"),
    "6620": ItemInfo("6620", "326620", "Ecos de Helia", "Echoes of Helia"),
    "6621": ItemInfo("6621", "326621", "Núcleo albar", "Dawncore"),
    "6657": ItemInfo("6657", "326657", "Vara de las edades", "Rod of Ages"),
    "8020": ItemInfo("8020", "328020", "Máscara abisal", "Abyssal Mask"),
}


@dataclass(frozen=True)
class RunStats:
    files_scanned: int = 0
    files_candidate_sr: int = 0
    files_modified: int = 0
    ids_replaced: int = 0


@dataclass
class ChangeSummary:
    champion: str
    old_id: str
    new_id: str
    name_es: str
    name_en: str
    count: int = 0


@dataclass
class RunResult:
    stats: RunStats = RunStats()
    # champion -> old_id -> count
    changes: Dict[str, Dict[str, int]] = field(default_factory=dict)
    modified_files: List[Path] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    root: Optional[Path] = None
    map_code: str = "SR"
    champions_detected: List[str] = field(default_factory=list)


def configure_console_encoding() -> None:
    """Make console output robust on Windows.

    Some Windows terminals default to legacy encodings (e.g. cp1252) that can't
    encode certain Unicode characters. We reconfigure stdout/stderr to UTF-8 and
    replace any unencodable chars.
    """

    for stream in (sys.stdout, sys.stderr):
        try:
            # Python 3.7+
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            # If reconfigure isn't available or fails, ignore; we'll also avoid
            # printing problematic characters.
            pass


def default_champions_root() -> Optional[Path]:
    """Try to locate League's Champions config folder on Windows."""

    # 1) If the script sits inside Champions (recommended for sharing), use that.
    here = Path(__file__).resolve().parent
    if here.exists() and here.is_dir() and any(here.glob("*/Recommended/*.json")):
        return here

    # 2) Common install paths.
    suffix = Path("Riot Games/League of Legends/Config/Champions")
    program_files = [
        Path(r"C:\Program Files"),
        Path(r"C:\Program Files (x86)"),
    ]

    candidates: List[Path] = []

    # Try drives (C..Z), but only a specific suffix (fast).
    for drive in string.ascii_uppercase:
        root = Path(f"{drive}:\\")
        if not root.exists():
            continue
        candidates.append(root / suffix)
        # También a veces está dentro de Program Files
        for pf in program_files:
            try:
                if str(pf).startswith(f"{drive}:\\"):
                    candidates.append(pf / suffix)
            except Exception:
                pass

    # Most common path first.
    candidates.insert(0, Path(r"C:\Riot Games\League of Legends\Config\Champions"))

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir() and any(candidate.glob("*/Recommended/*.json")):
            return candidate

    return None


def iter_itemset_json_files(root: Path) -> Iterable[Path]:
    # Champion folders are direct children; Recommended is inside each one.
    yield from root.glob("*/Recommended/*.json")


def _json_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _json_dump_minified(obj: Any, path: Path) -> None:
    # Riot's files are typically minified; keep similar formatting.
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def _champion_name_from_path(root: Path, json_path: Path) -> str:
    try:
        rel = json_path.relative_to(root)
        # <Champion>/Recommended/<file>.json
        return rel.parts[0] if rel.parts else json_path.parent.parent.name
    except ValueError:
        # root is not a prefix; infer
        return json_path.parent.parent.name


def replace_ids_in_itemset(
    obj: Any,
    id_map: Mapping[str, str],
    changes: MutableMapping[str, MutableMapping[str, int]],
    champion: str,
) -> Tuple[Any, int]:
    """Replace item IDs inside a Riot item set JSON object.

    Returns (possibly modified obj, replacements_count).
    """
    if not isinstance(obj, dict):
        return obj, 0

    blocks = obj.get("blocks")
    if not isinstance(blocks, list):
        return obj, 0

    replacements = 0

    for block in blocks:
        if not isinstance(block, dict):
            continue
        items = block.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            if raw_id is None:
                continue
            item_id = str(raw_id)
            new_id = id_map.get(item_id)
            if new_id and new_id != item_id:
                item["id"] = new_id
                replacements += 1
                champ_items = changes.setdefault(champion, {})
                champ_items[item_id] = champ_items.get(item_id, 0) + 1

    return obj, replacements


def process_file(
    path: Path,
    root: Path,
    id_map: Mapping[str, str],
    changes: MutableMapping[str, MutableMapping[str, int]],
    apply_changes: bool,
    backup: bool,
    map_code: str,
) -> Tuple[bool, int, str]:
    """Process one JSON file.

    Returns (is_candidate_map, replacements, error_message)
    """
    try:
        obj = _json_load(path)

        if not isinstance(obj, dict):
            return False, 0, "Unexpected JSON format (root is not an object)"

        if obj.get("map") != map_code:
            return False, 0, ""

        champion = _champion_name_from_path(root, path)
        obj, replacements = replace_ids_in_itemset(
            obj,
            id_map=id_map,
            changes=changes,
            champion=champion,
        )
        if replacements and apply_changes:
            if backup:
                backup_path = path.with_suffix(path.suffix + ".bak")
                if not backup_path.exists():
                    shutil.copy2(path, backup_path)
            _json_dump_minified(obj, path)

        return True, replacements, ""
    except json.JSONDecodeError as e:
        return False, 0, f"Invalid JSON: {e}"
    except OSError as e:
        return False, 0, f"I/O error: {e}"


def build_maps() -> Tuple[Dict[str, str], Dict[str, ItemInfo]]:
    """Return (old_id->new_id, old_id->ItemInfo)."""
    id_map: Dict[str, str] = {old_id: info.new_id for old_id, info in EMBEDDED_ITEM_MAP.items()}
    info_map: Dict[str, ItemInfo] = dict(EMBEDDED_ITEM_MAP)
    return id_map, info_map


def run_fix(
    root: Path,
    *,
    apply_changes: bool,
    backup: bool,
    map_code: str = "SR",
) -> RunResult:
    """Scan Champions/*/Recommended/*.json and replace IDs for a given map code."""

    id_map, _info_map = build_maps()
    result = RunResult(root=root, map_code=map_code)
    stats = RunStats()
    changes: Dict[str, Dict[str, int]] = {}
    champions_seen: set[str] = set()

    for json_path in iter_itemset_json_files(root):
        stats = RunStats(
            files_scanned=stats.files_scanned + 1,
            files_candidate_sr=stats.files_candidate_sr,
            files_modified=stats.files_modified,
            ids_replaced=stats.ids_replaced,
        )

        is_candidate, replacements, error = process_file(
            json_path,
            root=root,
            id_map=id_map,
            changes=changes,
            apply_changes=apply_changes,
            backup=backup,
            map_code=map_code,
        )
        if error:
            result.warnings.append(f"WARN: {json_path}: {error}")
            continue

        if not is_candidate:
            continue

        champions_seen.add(_champion_name_from_path(root, json_path))

        stats = RunStats(
            files_scanned=stats.files_scanned,
            files_candidate_sr=stats.files_candidate_sr + 1,
            files_modified=stats.files_modified + (1 if replacements else 0),
            ids_replaced=stats.ids_replaced + replacements,
        )
        if replacements:
            result.modified_files.append(json_path)

    result.stats = stats
    result.changes = changes
    result.champions_detected = sorted(champions_seen, key=str.casefold)
    return result


def flatten_changes(result: RunResult) -> List[ChangeSummary]:
    """Convert RunResult changes map to a flat list for printing/UI."""
    _id_map, info_map = build_maps()
    rows: List[ChangeSummary] = []
    for champion in sorted(result.changes.keys(), key=str.casefold):
        items_by_old_id = result.changes[champion]
        for old_id, count in sorted(items_by_old_id.items(), key=lambda kv: (-kv[1], kv[0])):
            info = info_map.get(old_id)
            if info is None:
                rows.append(ChangeSummary(champion, old_id, "?", f"ID {old_id}", f"ID {old_id}", count=count))
            else:
                rows.append(
                    ChangeSummary(
                        champion,
                        info.old_id,
                        info.new_id,
                        info.name_es,
                        info.name_en,
                        count=count,
                    )
                )
    return rows


def print_cli_report(result: RunResult, *, apply_changes: bool) -> None:
    id_map, info_map = build_maps()
    action = "MODIFIED" if apply_changes else "WOULD MODIFY"
    for p in result.modified_files:
        # Recompute per-file replacement count is expensive; keep simple.
        print(f"{action}: {p}")

    if result.warnings:
        for w in result.warnings:
            print(w)

    if result.champions_detected:
        print("Detected champions (map=%s): %s" % (result.map_code, ", ".join(result.champions_detected)))

    rows = flatten_changes(result)
    if rows:
        print("\nChanges by champion (SR 5v5):")
        current = None
        parts: List[str] = []
        for row in rows:
            if current != row.champion:
                if current is not None:
                    print(f"- {current}: " + "; ".join(parts))
                current = row.champion
                parts = []
            suffix = f" x{row.count}" if row.count != 1 else ""
            parts.append(f"{row.name_es} / {row.name_en} ({row.old_id}->{row.new_id}){suffix}")
        if current is not None:
            print(f"- {current}: " + "; ".join(parts))
    else:
        print("\nNo replacements matched the embedded mapping.")

    print(
        "\nSummary: "
        f"scanned={result.stats.files_scanned}, map={result.map_code}={result.stats.files_candidate_sr}, "
        f"files_changed={result.stats.files_modified}, ids_changed={result.stats.ids_replaced}"
    )


def start_gui() -> int:
    if not TK_AVAILABLE:
        print("ERROR: Tkinter is not available in this Python environment.")
        return 2

    configure_console_encoding()

    root_window = tk.Tk()
    root_window.title("LoL ItemSet ID Fixer (SR 5v5)")
    root_window.minsize(980, 620)

    # State
    default_root = default_champions_root()
    champions_path_var = tk.StringVar(value=str(default_root) if default_root else "")
    apply_var = tk.BooleanVar(value=True)
    backup_var = tk.BooleanVar(value=True)
    status_var = tk.StringVar(value="Ready")

    log_queue: Queue[str] = Queue()
    result_queue: Queue[Optional[RunResult]] = Queue()

    def log(msg: str) -> None:
        log_queue.put(msg)

    def browse_root() -> None:
        chosen = filedialog.askdirectory(title="Select Champions folder")
        if chosen:
            champions_path_var.set(chosen)

    def open_root_folder() -> None:
        p = champions_path_var.get().strip()
        if not p:
            return
        try:
            os.startfile(p)  # type: ignore[attr-defined]
        except Exception as e:
            messagebox.showerror("Open folder failed", str(e))

    # Layout
    top = ttk.Frame(root_window, padding=10)
    top.pack(fill="x")

    ttk.Label(top, text="Champions folder:").grid(row=0, column=0, sticky="w")
    entry = ttk.Entry(top, textvariable=champions_path_var, width=90)
    entry.grid(row=0, column=1, sticky="we", padx=8)
    ttk.Button(top, text="Browse...", command=browse_root).grid(row=0, column=2, padx=4)
    ttk.Button(top, text="Open", command=open_root_folder).grid(row=0, column=3, padx=4)
    top.columnconfigure(1, weight=1)

    options = ttk.Frame(root_window, padding=(10, 0, 10, 10))
    options.pack(fill="x")
    ttk.Checkbutton(options, text="Apply changes (write JSON)", variable=apply_var).grid(row=0, column=0, sticky="w")
    ttk.Checkbutton(options, text="Create .bak backups", variable=backup_var).grid(row=0, column=1, sticky="w", padx=12)
    ttk.Label(options, text="Map: SR (5v5) only").grid(row=0, column=2, sticky="w", padx=12)

    run_btn = ttk.Button(options, text="Run", width=14)
    run_btn.grid(row=0, column=3, sticky="e")
    options.columnconfigure(3, weight=1)

    mid = ttk.Panedwindow(root_window, orient="horizontal")
    mid.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # Table
    table_frame = ttk.Frame(mid)
    mid.add(table_frame, weight=3)
    columns = ("champion", "item_es", "item_en", "old_id", "new_id", "count")
    tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)
    tree.heading("champion", text="Champion")
    tree.heading("item_es", text="Item (ES)")
    tree.heading("item_en", text="Item (EN)")
    tree.heading("old_id", text="Old")
    tree.heading("new_id", text="New")
    tree.heading("count", text="Count")
    tree.column("champion", width=140, anchor="w")
    tree.column("item_es", width=260, anchor="w")
    tree.column("item_en", width=240, anchor="w")
    tree.column("old_id", width=70, anchor="center")
    tree.column("new_id", width=90, anchor="center")
    tree.column("count", width=60, anchor="center")

    yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=yscroll.set)
    tree.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")
    table_frame.rowconfigure(0, weight=1)
    table_frame.columnconfigure(0, weight=1)

    # Log
    log_frame = ttk.Frame(mid)
    mid.add(log_frame, weight=2)
    ttk.Label(log_frame, text="Output:").grid(row=0, column=0, sticky="w")
    log_text = tk.Text(log_frame, height=18, wrap="word")
    log_text.grid(row=1, column=0, sticky="nsew")
    log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=log_text.yview)
    log_text.configure(yscrollcommand=log_scroll.set)
    log_scroll.grid(row=1, column=1, sticky="ns")
    log_frame.rowconfigure(1, weight=1)
    log_frame.columnconfigure(0, weight=1)

    bottom = ttk.Frame(root_window, padding=(10, 0, 10, 10))
    bottom.pack(fill="x")
    ttk.Label(bottom, textvariable=status_var).pack(side="left")

    def clear_ui() -> None:
        for iid in tree.get_children():
            tree.delete(iid)
        log_text.delete("1.0", "end")

    def append_log(line: str) -> None:
        log_text.insert("end", line + "\n")
        log_text.see("end")

    def set_running(running: bool) -> None:
        state = "disabled" if running else "normal"
        run_btn.configure(state=state)

    def worker(champions_root: Path, apply_changes: bool, backup: bool) -> None:
        started = time.time()
        log(f"Root: {champions_root}")
        log(f"Mode: {'APPLY' if apply_changes else 'DRY-RUN'}; backups={'ON' if backup else 'OFF'}")
        try:
            res = run_fix(champions_root, apply_changes=apply_changes, backup=backup, map_code="SR")
            duration = time.time() - started
            log(f"Done in {duration:.2f}s")
            result_queue.put(res)
        except Exception as e:
            log(f"ERROR: {e}")
            result_queue.put(None)

    def on_run() -> None:
        p = champions_path_var.get().strip().strip('"')
        if not p:
            messagebox.showerror("Missing path", "Please select the Champions folder.")
            return
        champions_root = Path(p)
        if not champions_root.exists() or not champions_root.is_dir():
            messagebox.showerror("Invalid path", f"Not a folder: {champions_root}")
            return

        clear_ui()
        set_running(True)
        status_var.set("Running...")

        t = threading.Thread(target=worker, args=(champions_root, apply_var.get(), backup_var.get()), daemon=True)
        t.start()

    run_btn.configure(command=on_run)

    def pump() -> None:
        # Drain logs
        while True:
            try:
                line = log_queue.get_nowait()
            except Exception:
                break
            append_log(line)

        # Check result
        try:
            res = result_queue.get_nowait()
        except Exception:
            res = None

        if res is not None:
            # Fill table
            rows = flatten_changes(res)
            for r in rows:
                tree.insert("", "end", values=(r.champion, r.name_es, r.name_en, r.old_id, r.new_id, r.count))

            # Print warnings & summary
            for w in res.warnings:
                append_log(w)

            if res.champions_detected:
                append_log("Detected champions (SR): " + ", ".join(res.champions_detected))

            append_log(
                f"Summary: scanned={res.stats.files_scanned}, map={res.map_code}={res.stats.files_candidate_sr}, "
                f"files_changed={res.stats.files_modified}, ids_changed={res.stats.ids_replaced}"
            )
            if apply_var.get():
                append_log("Applied changes. Backups are created as .bak (if enabled).")
            else:
                append_log("Dry-run: no files were modified.")

            status_var.set("Done")
            set_running(False)

        root_window.after(100, pump)

    root_window.after(100, pump)
    root_window.mainloop()
    return 0


def main() -> int:
    # Default UX:
    # - If launched without CLI arguments (double-click / GUI exe), start GUI.
    # - Otherwise, run CLI.
    if len(sys.argv) == 1:
        return start_gui()

    configure_console_encoding()

    parser = argparse.ArgumentParser(
        description=(
            "LoL RIOT ItemSet ID Fixer (SR 5v5). Replaces selected item IDs in Champions/*/Recommended/*.json.\n"
            "Default behavior is to APPLY changes (writes JSON). Use --dry-run to simulate.\n"
            "GUI starts when launched without arguments."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help='Champions folder, e.g. "C:/Riot Games/League of Legends/Config/Champions" (auto-detected if omitted).',
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not write files; only report what would change")
    parser.add_argument("--no-backup", action="store_true", help="Do not create .bak when applying changes")
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Force GUI even when passing arguments",
    )
    args = parser.parse_args()

    if args.gui:
        return start_gui()

    champions_root: Optional[Path] = args.root or default_champions_root()
    if champions_root is None:
        print(
            "ERROR: Could not auto-detect Champions folder. Use --root with the correct path."
        )
        return 2
    if not champions_root.exists() or not champions_root.is_dir():
        print(f"ERROR: Not a folder: {champions_root}")
        return 2

    apply_changes = not args.dry_run
    backup = not args.no_backup

    result = run_fix(champions_root, apply_changes=apply_changes, backup=backup, map_code="SR")
    print_cli_report(result, apply_changes=apply_changes)
    if args.dry_run:
        print("\nDry-run: no files were modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
