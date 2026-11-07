"""Copies a real inspect run's raw output into tests/captures, removing the GPU UUID.

Only identifiers change. Every measured value stays exactly as captured.
Usage: python scripts/scrub_capture.py RAW_DIR DEST_DIR
"""
import re
import sys
from pathlib import Path

src, dest = Path(sys.argv[1]), Path(sys.argv[2])
dest.mkdir(parents=True, exist_ok=False)
for f in src.iterdir():
    text = f.read_text(encoding="utf-8")
    text = re.sub(r"GPU-[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", "GPU-SCRUBBED", text)
    (dest / f.name).write_text(text, encoding="utf-8")
print(f"Wrote {dest}")
