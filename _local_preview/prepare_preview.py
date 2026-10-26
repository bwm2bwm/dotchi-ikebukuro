#!/usr/bin/env python3
"""Safely build and publish a local-only real timetable preview from saved inputs."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path.home() / "Library" / "Application Support" / "dotchi-ikebukuro-preview" / "site"
SOURCE = ROOT / "_local_preview"
ADAPTER = ROOT / "scripts" / "timetable_adapter.mjs"
LOADER = ROOT / "scripts" / "local_preview_payload_loader.mjs"
EXPORTER = ROOT / "scripts" / "export_local_timetable_payload.py"
DATA_DIR = ROOT / "local_data" / "odpt"
REQUIRED_INPUTS = (
    DATA_DIR / "TokyoMetro-Train-GTFS.zip",
    DATA_DIR / "TrainTimetable_Yurakucho.json",
    DATA_DIR / "TrainTimetable_Fukutoshin.json",
    DATA_DIR / "Station_all.json",
)
PREVIEW_FILES = ("index.html", "preview.js", "preview.css", "selection.mjs", "terminal_ui.mjs", "virtual_now.mjs",
                 "performance_metrics.mjs")
DESTINATION_PAYLOADS = {
    "Kanamecho": "timetable-Kanamecho.json",
    "Senkawa": "timetable-Senkawa.json",
    "KotakeMukaihara": "timetable-KotakeMukaihara.json",
    "Hikawadai": "timetable.json",
    "Heiwadai": "timetable-Heiwadai.json",
    "ChikatetsuAkatsuka": "timetable-ChikatetsuAkatsuka.json",
    "ChikatetsuNarimasu": "timetable-ChikatetsuNarimasu.json",
    "Wakoshi": "timetable-Wakoshi.json",
}


def service_dates(now: datetime | None = None) -> list[date]:
    now = now or datetime.now(ZoneInfo("Asia/Tokyo"))
    today = now.astimezone(ZoneInfo("Asia/Tokyo")).date()
    return [today + timedelta(days=offset) for offset in (-1, 0, 1)]


def check_inputs() -> None:
    missing = [str(path) for path in REQUIRED_INPUTS if not path.is_file()]
    missing += [str(path) for path in (ROOT / "styles.css", ADAPTER, LOADER, EXPORTER, SOURCE / "validate_payload.mjs",
                                      *(SOURCE / name for name in PREVIEW_FILES))
                if not path.is_file()]
    if missing:
        raise FileNotFoundError("必要なローカル入力／preview source がありません: " + ", ".join(missing))


def prepare(*, now: datetime | None = None, output: Path = OUTPUT,
            exporter=subprocess.run, validator=subprocess.run, replace=os.replace) -> dict:
    """Build in the destination filesystem, validate, then swap with rollback."""
    check_inputs()
    output = output.expanduser().resolve()
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    days = service_dates(now)
    stage_root = Path(tempfile.mkdtemp(prefix=".dotchi-preview-stage-", dir=output.parent))
    stage = stage_root / "site"
    stage.mkdir(mode=0o700)
    backup = output.parent / (".dotchi-preview-backup-" + uuid.uuid4().hex)
    moved_old = False
    generation_seconds = 0.0
    validation_seconds = 0.0
    try:
        for name in PREVIEW_FILES:
            shutil.copy2(SOURCE / name, stage / name)
        shutil.copy2(ROOT / "styles.css", stage / "styles.css")
        shutil.copy2(ADAPTER, stage / "timetable_adapter.mjs")
        shutil.copy2(LOADER, stage / "local_preview_payload_loader.mjs")
        shutil.copy2(SOURCE / "validate_payload.mjs", stage / "validate_payload.mjs")
        for destination_id, filename in DESTINATION_PAYLOADS.items():
            payload_path = stage / filename
            command = [sys.executable, str(EXPORTER), "--destination-station-id", destination_id,
                       "--output", str(payload_path)]
            for day in days:
                command.extend(("--service-date", day.isoformat()))
            started = time.perf_counter()
            exporter(command, cwd=ROOT, check=True, capture_output=True, text=True)
            generation_seconds += time.perf_counter() - started
            payload_path.chmod(0o600)
            started = time.perf_counter()
            validator(["node", str(stage / "validate_payload.mjs"), str(payload_path)],
                      cwd=ROOT, check=True, capture_output=True, text=True)
            validation_seconds += time.perf_counter() - started
        payload_bytes = sum((stage / name).stat().st_size for name in DESTINATION_PAYLOADS.values())
        # copy2 preserves source timestamps; refresh the staged HTTP validators so
        # Safari sees updated modules after an atomic preview replacement.
        for staged_file in stage.iterdir():
            if staged_file.is_file():
                os.utime(staged_file, None)
        stage.chmod(0o700)

        if output.exists():
            replace(output, backup)
            moved_old = True
        try:
            replace(stage, output)
        except Exception:
            if moved_old:
                replace(backup, output)
                moved_old = False
            raise
        if moved_old:
            shutil.rmtree(backup)
            moved_old = False
        return {"output": output, "service_dates": days, "payload_count": len(DESTINATION_PAYLOADS),
                "payload_bytes": payload_bytes, "generation_seconds": generation_seconds,
                "validation_seconds": validation_seconds}
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        action = "payload生成" if str(EXPORTER) in " ".join(map(str, exc.cmd)) else "payload検証"
        raise RuntimeError(f"{action}に失敗しました" + (f": {detail}" if detail else "")
                           + "。既存previewは維持されました。") from exc
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def main() -> int:
    try:
        result = prepare()
    except Exception as exc:
        print(f"preview更新失敗: {exc}", file=sys.stderr)
        return 1
    print(f"ローカルpreview更新完了: {result['output']}")
    print("運行日: " + ", ".join(day.isoformat() for day in result["service_dates"]))
    print(f"目的地payload: {result['payload_count']}駅分、合計 {result['payload_bytes']:,} bytes")
    print(f"生成: {result['generation_seconds']:.1f}秒、検証: {result['validation_seconds']:.1f}秒")
    print("起動: python3 -m http.server 8765 --bind 127.0.0.1 --directory " + str(result["output"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
