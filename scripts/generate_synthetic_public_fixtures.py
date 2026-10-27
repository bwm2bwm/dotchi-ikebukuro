#!/usr/bin/env python3
"""Generate CI-ready public-display-v1 payload fixtures from tracked synthetic test data."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

from synthetic_public_fixture_factory import (
    SyntheticFixtureError,
    generate_fixture_directory,
    jst_today,
    parse_service_date,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path,
                        help="new output directory; an existing path is never overwritten")
    parser.add_argument("--service-date", metavar="YYYY-MM-DD",
                        help="anchor date; defaults to the current calendar date in Asia/Tokyo")
    args = parser.parse_args()
    try:
        anchor_date: date = parse_service_date(args.service_date) if args.service_date else jst_today()
        result = generate_fixture_directory(args.output, anchor_date)
    except (SyntheticFixtureError, OSError) as error:
        print(f"synthetic fixture generation failed: {error}", file=sys.stderr)
        return 1
    print(f"Synthetic fixtures generated: {result['output']}")
    print(f"Stations: {result['stations']}; serviceDate: {', '.join(result['service_dates'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
