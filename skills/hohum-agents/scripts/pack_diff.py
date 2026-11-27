#!/usr/bin/env python3
"""
Deterministic dumb-node script: pack BASE..HEAD commits, diffstat, and unified diff
into a single review package file under .agent/tasks/ so raw diff never bloats Lead context.

Hardened guarantees:
- Resolves BASE and HEAD once to fixed 40-char commit SHAs (no drifting literal HEAD).
- Refuses empty diffs (BASE == HEAD) unless --allow-empty is explicitly passed.
- Refuses dirty working trees (uncommitted/untracked non-.agent changes) unless --allow-dirty
  is explicitly passed, preventing Checker from reviewing different code than what was tested.
- Optionally embeds verification command/exit-code/log metadata bound to the exact HEAD SHA.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_MAX_BYTES = 512 * 1024  # 512 KiB safeguard against bloating Checker context


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


def resolve_commit(ref: str, cwd: Path) -> str:
    return run_git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd).strip()


def list_dirty_files(cwd: Path, ignore_prefixes: tuple[str, ...] = (".agent/",)) -> list[str]:
    raw = run_git(["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd)
    dirty: list[str] = []
    tokens = raw.split("\x00")
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok:
            i += 1
            continue
        xy = tok[:2]
        rel = (tok[3:] if len(tok) >= 4 else "").replace("\\", "/")
        while rel.startswith("./"):
            rel = rel[2:]
        if rel and not any(rel.startswith(p) or rel == p.rstrip("/") for p in ignore_prefixes):
            dirty.append(rel)
        if xy and (xy[0] in ("R", "C") or xy[1] in ("R", "C")):
            i += 2
        else:
            i += 1
    return sorted(set(dirty))


def _summarize_numstat(numstat_out: str) -> tuple[list[dict[str, Any]], list[tuple[str, int, int, int]]]:
    files: list[dict[str, Any]] = []
    dir_totals: dict[str, list[int]] = {}
    for line in numstat_out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        add_s, del_s, path = parts[0], parts[1], parts[2].replace("\\", "/")
        binary = add_s == "-" or del_s == "-"
        added = 0 if binary else int(add_s)
        deleted = 0 if binary else int(del_s)
        files.append({"path": path, "added": added, "deleted": deleted, "binary": binary})
        top = path.split("/", 1)[0] if "/" in path else "(root)"
        bucket = dir_totals.setdefault(top, [0, 0, 0])
        bucket[0] += 1
        bucket[1] += added
        bucket[2] += deleted
    dir_summary = sorted(
        ((k, v[0], v[1], v[2]) for k, v in dir_totals.items()),
        key=lambda item: (-item[2] - item[3], item[0]),
    )
    return files, dir_summary


def _has_parent_commit(commit_sha: str, cwd: Path) -> bool:
    res = subprocess.run(
        ["git", "rev-parse", "--verify", f"{commit_sha}^"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return res.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack BASE..HEAD into a single bound review diff file")
    parser.add_argument("--cwd", default=".", help="Git repository root")
    parser.add_argument("--base", required=True, help="Base commit SHA/ref (slice base or branch base for --whole-branch)")
    parser.add_argument("--head", default="HEAD", help="Head commit SHA/ref (default: HEAD)")
    parser.add_argument("--out", required=True, help="Output file path, e.g. .agent/tasks/task-1-review.diff")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow packing when uncommitted non-.agent changes exist")
    parser.add_argument("--allow-empty", action="store_true", help="Allow packing when BASE..HEAD diff is empty")
    parser.add_argument(
        "--whole-branch",
        action="store_true",
        help="Generate a whole-branch final review brief (branch base -> final HEAD) with full change inventory and cross-slice contract audit checklist",
    )
    parser.add_argument(
        "--dataflow",
        action="append",
        default=[],
        help="With --whole-branch: critical end-to-end dataflow to spot-check across slices (repeatable, e.g. 'input -> mask segments -> export')",
    )
    parser.add_argument(
        "--no-diff",
        action="store_true",
        help="With --whole-branch: omit inline unified diff and rely on full inventory + direct repo file inspection",
    )
    parser.add_argument("--verify-cmd", help="Optional verification command executed against HEAD")
    parser.add_argument("--verify-exit-code", type=int, help="Optional exit code of the verification command")
    parser.add_argument("--verify-log", help="Optional path to the verification log file")
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help="Maximum unified diff bytes before truncation (0 disables limit)",
    )
    parser.add_argument("--json", action="store_true", help="Print structured JSON metadata instead of only path")
    args = parser.parse_args()

    cwd = Path(args.cwd).resolve()
    try:
        base_sha = resolve_commit(args.base, cwd)
        head_sha = resolve_commit(args.head, cwd)
        dirty_files = list_dirty_files(cwd)
    except RuntimeError as exc:
        print(f"[pack_diff ERROR] {exc}", file=sys.stderr)
        return 2

    if dirty_files and not args.allow_dirty:
        preview = ", ".join(dirty_files[:10])
        more = f" (+{len(dirty_files) - 10} more)" if len(dirty_files) > 10 else ""
        print(
            f"[pack_diff ERROR] Refusing to pack with uncommitted changes ({len(dirty_files)} files: {preview}{more}). "
            "Commit or stash slice changes so Checker reviews the exact code that was tested, or pass --allow-dirty.",
            file=sys.stderr,
        )
        return 2

    rev_range = f"{base_sha}..{head_sha}"
    try:
        log_out = run_git(["log", "--oneline", rev_range], cwd)
        stat_out = run_git(["diff", "--stat", rev_range], cwd)
        numstat_out = run_git(["diff", "--numstat", rev_range], cwd)
        names_out = run_git(["diff", "--name-only", rev_range], cwd)
        diff_out = "" if (args.whole_branch and args.no_diff) else run_git(["diff", "-U10", rev_range], cwd)
    except RuntimeError as exc:
        print(f"[pack_diff ERROR] {exc}", file=sys.stderr)
        return 2

    commits = [line.strip() for line in log_out.splitlines() if line.strip()]
    files_changed = [line.strip() for line in names_out.splitlines() if line.strip()]
    if (base_sha == head_sha or (not files_changed and not diff_out.strip())) and not args.allow_empty:
        print(
            f"[pack_diff ERROR] Empty diff for {rev_range} (no committed changes to review). "
            "Ensure Builder committed its slice changes, or pass --allow-empty.",
            file=sys.stderr,
        )
        return 3

    numstat_files, dir_summary = _summarize_numstat(numstat_out)
    single_commit_warning: str | None = None
    if args.whole_branch and len(commits) <= 1 and _has_parent_commit(base_sha, cwd):
        single_commit_warning = (
            "Whole-branch range contains <=1 commit while base has parent commits; "
            "verify --base is the true feature branch base SHA and not merely the last slice base."
        )

    diff_bytes = len(diff_out.encode("utf-8"))
    truncated = False
    rendered_diff = diff_out
    if args.max_bytes > 0 and diff_bytes > args.max_bytes:
        truncated = True
        rendered_diff = diff_out.encode("utf-8")[: args.max_bytes].decode("utf-8", errors="ignore")
        rendered_diff += (
            f"\n\n... [TRUNCATED: unified diff was {diff_bytes} bytes, cap={args.max_bytes} bytes; "
            f"total changed files={len(files_changed)}] ...\n"
        )

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = cwd / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    verify_lines: list[str] = [f"- Tested/Reviewed Commit: `{head_sha}`"]
    if args.verify_cmd is not None:
        verify_lines.append(f"- Verify Command: `{args.verify_cmd}`")
    if args.verify_exit_code is not None:
        verify_lines.append(f"- Verify Exit Code: `{args.verify_exit_code}`")
    if args.verify_log is not None:
        verify_lines.append(f"- Verify Log: `{args.verify_log}`")
    if dirty_files:
        verify_lines.append(f"- Working Tree: DIRTY (--allow-dirty used; {len(dirty_files)} uncommitted files)")
    else:
        verify_lines.append("- Working Tree: CLEAN (no uncommitted non-.agent changes)")

    if args.whole_branch:
        dir_lines = [
            f"| `{d}` | {cnt} | +{add} | -{rem} |" for d, cnt, add, rem in dir_summary
        ] or ["| `(none)` | 0 | +0 | -0 |"]
        inventory_lines = []
        for f in numstat_files:
            delta = "binary" if f["binary"] else f"+{f['added']}/-{f['deleted']}"
            inventory_lines.append(f"- `{f['path']}` ({delta})")
        if not inventory_lines:
            inventory_lines = ["- (none)"]
        flows = [df.strip() for df in args.dataflow if df.strip()] or [
            "Trace primary end-to-end contract path across slices (input -> core transform/state -> output/persistence)."
        ]
        flow_lines = [f"- [ ] {df}" for df in flows]
        warn_block = f"\n> **SCOPE WARNING**: {single_commit_warning}\n" if single_commit_warning else ""
        diff_section = (
            "## Unified Diff\n_(Omitted via `--no-diff`; inspect source files directly along the cross-slice dataflows above.)_\n"
            if args.no_diff
            else f"## Unified Diff (-U10)\n```diff\n{rendered_diff}\n```\n"
        )
        diff_bytes_label = (
            "omitted (--no-diff)"
            if args.no_diff
            else f"{diff_bytes}{' (TRUNCATED)' if truncated else ''}"
        )
        content = (
            f"# Whole-Branch Final Review Package ({rev_range})\n\n"
            f"- Review Scope: **WHOLE-BRANCH** (do NOT treat a single-slice diff as whole-branch evidence)\n"
            f"- Branch Base SHA: `{base_sha}`\n"
            f"- Final Head SHA: `{head_sha}`\n"
            f"- Commits in Range: {len(commits)}\n"
            f"- Changed Files (Complete, Never Truncated): {len(files_changed)}\n"
            f"- Unified Diff Bytes: {diff_bytes_label}\n"
            f"{warn_block}\n"
            f"## Verification Binding\n"
            + "\n".join(verify_lines)
            + "\n\n"
            f"## Cross-Slice Contract Audit & Required Coverage Disclosure\n"
            f"Inspect live repository files directly along these end-to-end boundaries:\n"
            + "\n".join(flow_lines)
            + "\n\n"
            f"In your review reply, explicitly include a **Coverage Scope** section separating:\n"
            f"1. Files / cross-slice contracts directly inspected in full\n"
            f"2. Areas relied on via prior slice reviews or automated tests (not re-read line-by-line)\n\n"
            f"## Commits ({len(commits)})\n```\n{log_out.strip() or '(no commits)'}\n```\n\n"
            f"## Directory Summary\n"
            f"| Top-Level Area | Files | Added | Deleted |\n"
            f"| :--- | ---: | ---: | ---: |\n"
            + "\n".join(dir_lines)
            + "\n\n"
            f"## Full Changed File Inventory ({len(files_changed)})\n"
            + "\n".join(inventory_lines)
            + "\n\n"
            + diff_section
        )
    else:
        content = (
            f"# Review Package ({rev_range})\n\n"
            f"- Base SHA: `{base_sha}`\n"
            f"- Head SHA: `{head_sha}`\n"
            f"- Changed Files: {len(files_changed)}\n"
            f"- Unified Diff Bytes: {diff_bytes}{' (TRUNCATED)' if truncated else ''}\n\n"
            f"## Verification Binding\n"
            + "\n".join(verify_lines)
            + "\n\n"
            f"## Commits\n```\n{log_out.strip() or '(no commits)'}\n```\n\n"
            f"## Diff Stat\n```\n{stat_out.strip() or '(empty)'}\n```\n\n"
            f"## Unified Diff (-U10)\n```diff\n{rendered_diff}\n```\n"
        )
    out_path.write_text(content, encoding="utf-8")

    meta: dict[str, Any] = {
        "ok": True,
        "whole_branch": bool(args.whole_branch),
        "out_path": str(out_path),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "commit_count": len(commits),
        "files_changed": files_changed,
        "dirty_files": dirty_files,
        "diff_bytes": diff_bytes,
        "truncated": truncated,
    }
    if single_commit_warning:
        meta["single_commit_warning"] = single_commit_warning
    if args.json:
        print(json.dumps(meta, ensure_ascii=False, indent=2))
    else:
        print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
