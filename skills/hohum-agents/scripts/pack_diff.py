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


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack BASE..HEAD into a single bound review diff file")
    parser.add_argument("--cwd", default=".", help="Git repository root")
    parser.add_argument("--base", required=True, help="Base commit SHA/ref recorded before Builder started")
    parser.add_argument("--head", default="HEAD", help="Head commit SHA/ref (default: HEAD)")
    parser.add_argument("--out", required=True, help="Output file path, e.g. .agent/tasks/task-1-review.diff")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow packing when uncommitted non-.agent changes exist")
    parser.add_argument("--allow-empty", action="store_true", help="Allow packing when BASE..HEAD diff is empty")
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
        names_out = run_git(["diff", "--name-only", rev_range], cwd)
        diff_out = run_git(["diff", "-U10", rev_range], cwd)
    except RuntimeError as exc:
        print(f"[pack_diff ERROR] {exc}", file=sys.stderr)
        return 2

    files_changed = [line.strip() for line in names_out.splitlines() if line.strip()]
    if (base_sha == head_sha or not diff_out.strip()) and not args.allow_empty:
        print(
            f"[pack_diff ERROR] Empty diff for {rev_range} (no committed changes to review). "
            "Ensure Builder committed its slice changes, or pass --allow-empty.",
            file=sys.stderr,
        )
        return 3

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
        "out_path": str(out_path),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "files_changed": files_changed,
        "dirty_files": dirty_files,
        "diff_bytes": diff_bytes,
        "truncated": truncated,
    }
    if args.json:
        print(json.dumps(meta, ensure_ascii=False, indent=2))
    else:
        print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
