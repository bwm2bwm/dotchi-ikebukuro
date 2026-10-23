#!/usr/bin/env python3
"""Build a persistent, local-only real timetable preview from saved inputs."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path.home() / "Library" / "Application Support" / "dotchi-ikebukuro-preview" / "site"
SOURCE = ROOT / "_local_preview"
ADAPTER = ROOT / "scripts" / "timetable_adapter.mjs"
EXPORTER = ROOT / "scripts" / "export_local_timetable_payload.py"


def main() -> int:
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    service_dates = [today + timedelta(days=offset) for offset in (-1, 0, 1)]
    OUTPUT.mkdir(mode=0o700, parents=True, exist_ok=True)
    OUTPUT.chmod(0o700)
    for name in ("index.html", "preview.js", "preview.css", "selection.mjs"):
        shutil.copy2(SOURCE / name, OUTPUT / name)
    shutil.copy2(ADAPTER, OUTPUT / "timetable_adapter.mjs")
    shutil.copy2(ROOT / "scripts" / "local_preview_payload_loader.mjs", OUTPUT / "local_preview_payload_loader.mjs")
    payload_path = OUTPUT / "timetable.json"
    payload_path.unlink(missing_ok=True)
    command = [sys.executable, str(EXPORTER), "--output", str(payload_path)]
    for service_date in service_dates:
        command.extend(("--service-date", service_date.isoformat()))
    subprocess.run(command, cwd=ROOT, check=True)
    payload_path.chmod(0o600)
    print(f"ローカルpreview: {OUTPUT}")
    print("起動: python3 -m http.server 8765 --bind 127.0.0.1 --directory " + str(OUTPUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
