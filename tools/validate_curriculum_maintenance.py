#!/usr/bin/env python3
"""Fail when a declared curriculum-maintenance review is overdue or inconsistent."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "catalog" / "curriculum-maintenance.json"
EXPECTED_AREAS = {
    "catalog-provenance",
    "locked-dependencies",
    "companion-accuracy",
    "readme-links",
    "safety-cost-accessibility",
}


def validate(policy_path: Path = DEFAULT_POLICY, today: date | None = None) -> list[dict[str, Any]]:
    current = today or date.today()
    try:
        policy = json.loads(policy_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read maintenance policy: {error}") from error
    if not isinstance(policy, dict) or set(policy) != {"schema_version", "areas"} or policy["schema_version"] != 1:
        raise ValueError("maintenance policy must be schema version 1 with areas")
    areas = policy["areas"]
    if not isinstance(areas, list) or {area.get("id") for area in areas if isinstance(area, dict)} != EXPECTED_AREAS:
        raise ValueError("maintenance policy must define the exact required areas")
    for area in areas:
        required_fields = {"id", "owner", "cadence_days", "last_reviewed", "next_due"}
        if not required_fields <= set(area) <= required_fields | {"review_evidence"}:
            raise ValueError(f"maintenance area has unexpected fields: {area.get('id')}")
        if "review_evidence" in area:
            reference = area["review_evidence"]
            if not isinstance(reference, str) or not reference.strip():
                raise ValueError(f"maintenance evidence reference missing: {area['id']}")
            relative = PurePosixPath(reference)
            evidence = ROOT / relative
            if relative.is_absolute() or ".." in relative.parts or not evidence.resolve().is_relative_to(ROOT.resolve()):
                raise ValueError(f"maintenance evidence must stay within the repository: {area['id']}")
            if not evidence.is_file():
                raise ValueError(f"maintenance evidence file missing: {area['id']}: {reference}")
        if not isinstance(area["owner"], str) or not area["owner"].strip():
            raise ValueError(f"maintenance owner missing: {area['id']}")
        if not isinstance(area["cadence_days"], int) or area["cadence_days"] <= 0:
            raise ValueError(f"maintenance cadence invalid: {area['id']}")
        try:
            reviewed = date.fromisoformat(area["last_reviewed"])
            due = date.fromisoformat(area["next_due"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"maintenance dates invalid: {area['id']}") from error
        if due != reviewed + timedelta(days=area["cadence_days"]):
            raise ValueError(f"maintenance next_due does not match cadence: {area['id']}")
        if reviewed > current:
            raise ValueError(f"maintenance last_reviewed is in the future: {area['id']}")
        if current > due:
            raise ValueError(f"maintenance overdue: {area['id']} owner={area['owner']} due={due.isoformat()}")
    return areas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--today", type=date.fromisoformat)
    args = parser.parse_args()
    try:
        areas = validate(args.policy, args.today)
    except ValueError as error:
        print(f"curriculum maintenance validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    next_area = min(areas, key=lambda area: area["next_due"])
    print(f"curriculum maintenance current: {len(areas)} areas; next={next_area['id']} due={next_area['next_due']}")


if __name__ == "__main__":
    main()
