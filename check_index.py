"""Quick diagnostic: shows file index status and lets you search."""
import sys, time, os
sys.path.insert(0, os.path.dirname(__file__))

from tools.file_indexer import get_indexer, _PRIORITY_FOLDERS

indexer = get_indexer()

print("Starting file system indexer...")
print(f"Priority folders being scanned:")
for f in _PRIORITY_FOLDERS:
    exists = "OK" if f.exists() else "NOT FOUND"
    print(f"  [{exists}] {f}")

indexer.start()

# Wait for priority scan to finish (Desktop/Downloads/Documents/Pictures/Videos)
print("\nWaiting for priority scan to complete", end="", flush=True)
for _ in range(30):
    if indexer.is_ready():
        break
    print(".", end="", flush=True)
    time.sleep(1)
print()

stats = indexer.stats()
print(f"\n--- Index Status ---")
print(f"  Ready:          {stats['ready']}")
print(f"  Still scanning: {stats['scanning']}")
print(f"  Files indexed:  {stats['filenames_indexed']:,}")

# Sample from Desktop, Downloads, Documents
print(f"\n--- Sample files from your Desktop ---")
results = indexer.search("", max_results=0)  # won't work with empty query

# Direct scan of priority folders for display
from pathlib import Path
for folder_name, folder_path in [("Desktop", Path.home()/"Desktop"),
                                   ("Downloads", Path.home()/"Downloads"),
                                   ("Documents", Path.home()/"Documents")]:
    if folder_path.exists():
        files = list(folder_path.iterdir())[:10]
        print(f"\n  {folder_name} ({folder_path}):")
        for f in files:
            kind = "[DIR] " if f.is_dir() else "[FILE]"
            print(f"    {kind} {f.name}")
        if len(list(folder_path.iterdir())) > 10:
            total = sum(1 for _ in folder_path.iterdir())
            print(f"    ... and {total - 10} more")

# Interactive search
print("\n--- Search Test ---")
print("Type a filename to search (or press Enter to skip):")
while True:
    try:
        query = input("  Search> ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if not query:
        break
    results = indexer.search(query)
    if not results:
        print(f"  No files found for '{query}'")
    else:
        print(f"  Found {len(results)} result(s):")
        for r in results:
            print(f"    {r['name']}")
            print(f"      Path: {r['path']}")

print("\nDone. Full drive scan continues in background.")
print(f"Final index size: {indexer.stats()['filenames_indexed']:,} filenames")
