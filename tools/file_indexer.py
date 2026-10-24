"""File system indexer — scans the computer and keeps a searchable index of all files."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

INDEX_PATH = "data/file_index.json"
REBUILD_INTERVAL = 1800  # 30 minutes

# Scan these first — fast, contains most user files
_PRIORITY_FOLDERS: list[Path] = [
    Path.home() / "Desktop",
    Path.home() / "Downloads",
    Path.home() / "Documents",
    Path.home() / "Pictures",
    Path.home() / "Videos",
    Path.home() / "Music",
    Path.home() / "OneDrive",
]

# Skip these during full-drive scan — system/program dirs with no user files
_SKIP_DIRS = {
    "windows", "$recycle.bin", "programdata", "program files",
    "program files (x86)", "system volume information", ".git",
    "node_modules", "__pycache__", ".cache", "appdata",
}


class FileIndexer:
    """Maintains an in-memory + on-disk index mapping filenames to their full paths."""

    def __init__(self) -> None:
        # index[filename_lower] = [full_path, ...]
        self._index: dict[str, list[str]] = {}
        self._lock = threading.RLock()
        self._ready = False
        self._scanning = False

    def start(self) -> None:
        self._load_from_disk()
        t = threading.Thread(target=self._background_loop, name="FileIndexer", daemon=True)
        t.start()

    def _load_from_disk(self) -> None:
        try:
            with open(INDEX_PATH, encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._index = data
                self._ready = True
            log.info("FileIndexer: loaded %d filenames from disk cache", len(self._index))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    def _save_to_disk(self) -> None:
        try:
            with self._lock:
                snapshot = dict(self._index)
            with open(INDEX_PATH, "w", encoding="utf-8") as f:
                json.dump(snapshot, f)
        except Exception as exc:
            log.warning("FileIndexer: save failed: %s", exc)

    def _background_loop(self) -> None:
        while True:
            self._rebuild()
            time.sleep(REBUILD_INTERVAL)

    def _rebuild(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        log.info("FileIndexer: starting scan...")
        new_index: dict[str, list[str]] = {}

        # Phase 1 — priority folders (fast, ~seconds)
        for folder in _PRIORITY_FOLDERS:
            if folder.exists():
                self._scan_dir(str(folder), new_index, skip_names=set())

        with self._lock:
            self._index = dict(new_index)
            self._ready = True
        log.info("FileIndexer: priority scan done — %d filenames indexed", len(new_index))

        # Phase 2 — full user profile (medium, covers most things the user cares about)
        user_root = str(Path.home())
        self._scan_dir(user_root, new_index, skip_names={"appdata", ".git", "__pycache__", "node_modules"})

        # Phase 3 — full C: drive (slow, background)
        try:
            self._scan_dir("C:\\", new_index, skip_names=_SKIP_DIRS)
        except Exception as exc:
            log.debug("FileIndexer: C: scan error: %s", exc)

        # Also scan other drives (D:, E:, ...)
        import string
        for drive_letter in string.ascii_uppercase:
            drive = f"{drive_letter}:\\"
            if drive == "C:\\":
                continue
            if os.path.exists(drive):
                try:
                    self._scan_dir(drive, new_index, skip_names=_SKIP_DIRS)
                except Exception:
                    pass

        with self._lock:
            self._index = dict(new_index)
        self._save_to_disk()
        self._scanning = False
        log.info("FileIndexer: full scan complete — %d filenames indexed", len(new_index))

    def _scan_dir(self, root: str, index: dict[str, list[str]], skip_names: set[str]) -> None:
        try:
            for dirpath, dirnames, filenames in os.walk(root, topdown=True):
                # Prune skipped dirs in-place so os.walk doesn't descend into them
                dirnames[:] = [
                    d for d in dirnames
                    if d.lower() not in skip_names and not d.startswith(".")
                ]
                for fname in filenames:
                    key = fname.lower()
                    full = os.path.join(dirpath, fname)
                    if key not in index:
                        index[key] = [full]
                    else:
                        index[key].append(full)
        except PermissionError:
            pass
        except Exception as exc:
            log.debug("FileIndexer: scan error in %s: %s", root, exc)

    def search(self, query: str, max_results: int = 15) -> list[dict]:
        """Return files matching query. Sorted: priority folders first."""
        q = query.lower().strip()
        if not q:
            return []

        results: list[dict] = []
        seen: set[str] = set()

        with self._lock:
            if not self._index:
                return []

            # 1. Exact filename match
            for path in self._index.get(q, []):
                if path not in seen:
                    results.append(_entry(path))
                    seen.add(path)

            # 2. Extension-only search (e.g. query=".pdf")
            if q.startswith("."):
                for key, paths in self._index.items():
                    if key.endswith(q):
                        for path in paths:
                            if path not in seen:
                                results.append(_entry(path))
                                seen.add(path)
                            if len(results) >= max_results:
                                break

            # 3. Partial/contains match
            for key, paths in self._index.items():
                if q in key and key != q:
                    for path in paths:
                        if path not in seen:
                            results.append(_entry(path))
                            seen.add(path)
                if len(results) >= max_results * 2:
                    break

        # Sort: priority folders first, then by path length (shorter = more accessible)
        priority_roots = [str(f).lower() for f in _PRIORITY_FOLDERS if f.exists()]

        def _rank(e: dict) -> tuple:
            p = e["path"].lower()
            is_priority = any(p.startswith(r) for r in priority_roots)
            return (0 if is_priority else 1, len(e["path"]))

        results.sort(key=_rank)
        return results[:max_results]

    def is_ready(self) -> bool:
        return self._ready

    def rebuild(self) -> None:
        t = threading.Thread(target=self._rebuild, name="FileIndexer-manual", daemon=True)
        t.start()

    def stats(self) -> dict:
        with self._lock:
            return {"filenames_indexed": len(self._index), "ready": self._ready, "scanning": self._scanning}


def _entry(path: str) -> dict:
    return {
        "name": os.path.basename(path),
        "path": path,
        "folder": os.path.dirname(path),
    }


_indexer: FileIndexer | None = None
_indexer_lock = threading.Lock()


def get_indexer() -> FileIndexer:
    global _indexer
    if _indexer is None:
        with _indexer_lock:
            if _indexer is None:
                _indexer = FileIndexer()
    return _indexer
