#!/usr/bin/env python3
"""
Deterministic dumb-node script: pack BASE..HEAD commits, diffstat, and unified diff
into a single review package file under .agent/tasks/ so raw diff never bloats Lead context.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_git(args: list[str], cwd: Path) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack BASE..HEAD into a single review diff file")
    parser.add_argument("--cwd", default=".", help="Git repository root")
    parser.add_argument("--base", required=True, help="Base commit SHA recorded before Builder started")
    parser.add_argument("--head", default="HEAD", help="Head commit SHA (default: HEAD)")
    parser.add_argument("--out", required=True, help="Output file path, e.g. .agent/tasks/task-1-review.diff")
    args = parser.parse_args()

    cwd = Path(args.cwd).resolve()
    rev_range = f"{args.base}..{args.head}"
    log_out = run_git(["log", "--oneline", rev_range], cwd)
    stat_out = run_git(["diff", "--stat", rev_range], cwd)
    diff_out = run_git(["diff", "-U10", rev_range], cwd)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = cwd / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    content = (
        f"# Review Package ({rev_range})\n\n"
        f"## Commits\n```\n{log_out.strip() or '(no commits)'}\n```\n\n"
        f"## Diff Stat\n```\n{stat_out.strip() or '(empty)'}\n```\n\n"
        f"## Unified Diff (-U10)\n```diff\n{diff_out}\n```\n"
    )
    out_path.write_text(content, encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
