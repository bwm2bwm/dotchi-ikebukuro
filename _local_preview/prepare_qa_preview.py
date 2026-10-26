#!/usr/bin/env python3
"""Build a local-only preview for virtual-time QA without replacing the regular preview."""
from __future__ import annotations

import argparse
from datetime import date, datetime, time
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

import prepare_preview

QA_ROOT = (Path.home() / "Library" / "Application Support" /
           "dotchi-ikebukuro-preview" / "qa")


def generate(target: str, *, prepare=prepare_preview.prepare) -> dict:
    """Generate target−1/target/target+1 service days in that target's QA folder."""
    target_date = date.fromisoformat(target)
    if target_date.isoformat() != target:
        raise ValueError("QA対象日は YYYY-MM-DD 形式で指定してください")
    # Use local noon as a stable anchor; prepare_preview derives service dates in JST.
    anchor = datetime.combine(target_date, time(12), tzinfo=ZoneInfo("Asia/Tokyo"))
    output = QA_ROOT / target_date.isoformat() / "site"
    def validate_at_target(command, **kwargs):
        return subprocess.run([*command, "--now", anchor.isoformat()], **kwargs)

    result = prepare(now=anchor, output=output, validator=validate_at_target)
    expected = [target_date.fromordinal(target_date.toordinal() + offset)
                for offset in (-1, 0, 1)]
    if result["service_dates"] != expected:
        raise RuntimeError("生成された運行日範囲がQA対象日と一致しません")
    result["target_date"] = target_date
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-date", default="2026-10-27", help="QA対象日 YYYY-MM-DD")
    args = parser.parse_args()
    try:
        result = generate(args.target_date)
    except Exception as exc:
        print(f"QA preview生成失敗: {exc}", file=sys.stderr)
        return 1
    print(f"QA preview更新完了: {result['output']}")
    print("対象日: " + result["target_date"].isoformat())
    print("運行日: " + ", ".join(day.isoformat() for day in result["service_dates"]))
    print(f"目的地payload: {result['payload_count']}駅分、合計 {result['payload_bytes']:,} bytes")
    print(f"生成: {result['generation_seconds']:.1f}秒、検証: {result['validation_seconds']:.1f}秒")
    print("起動: python3 -m http.server 8765 --bind 127.0.0.1 --directory " + str(result["output"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
