from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove that a reliability report was produced from the checked-out source.")
    parser.add_argument("--commit", default="", help="Expected checkout commit, normally github.sha.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-current-ref", action="store_true")
    args = parser.parse_args()

    head = git_value("rev-parse", "HEAD")
    expected = str(args.commit or "").strip()
    clean = not bool(git_value("status", "--porcelain"))
    matches = not expected or head == expected
    passed = clean and matches
    report = {
        "schema_version": 1,
        "status": "pass" if passed else "fail",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "commit": head,
        "expected_commit": expected,
        "matches_expected_commit": matches,
        "clean_checkout": clean,
        "require_current_ref": bool(args.require_current_ref),
        "source": "git checkout",
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if args.require_current_ref and not matches:
        return 1
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
