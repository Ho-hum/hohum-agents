#!/usr/bin/env python3
"""
Portable hardened CLI bridge for hohum-agents.
Loads role definitions from roles.local.json (git-ignored) if present,
falling back to roles.example.json. Zero third-party dependencies (Python 3.10+).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
CHECKER_ROLES = {"checker", "checker-fallback"}
DEFAULT_AUDIT_IGNORE_PREFIXES = (".agent/logs/",)


def load_roles(config_path: Path | None = None) -> dict[str, dict[str, Any]]:
    if config_path is not None:
        path = config_path
    elif (SCRIPT_DIR / "roles.local.json").exists():
        path = SCRIPT_DIR / "roles.local.json"
    else:
        path = SCRIPT_DIR / "roles.example.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid roles config in {path}: expected top-level JSON object")
    return data


def resolve_bin(env_var: str, command_name: str) -> str | None:
    override = os.environ.get(env_var, "").strip()
    if override and Path(override).exists():
        return str(Path(override))
    found = shutil.which(command_name)
    return str(Path(found)) if found else None


def _run_git(args: list[str], cwd: Path, timeout: int = 15, text: bool = True) -> subprocess.CompletedProcess[Any] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=text,
            encoding="utf-8" if text else None,
            errors="replace" if text else None,
            timeout=timeout,
        )
    except Exception:
        return None


def _sha256_file(path: Path) -> str:
    try:
        if path.is_symlink():
            return f"symlink:{os.readlink(path)}"
        if not path.exists():
            return "missing"
        if path.is_dir():
            return "dir"
        h = hashlib.sha256()
        with path.open("rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError as exc:
        return f"error:{exc.__class__.__name__}"


def _parse_porcelain_z(raw: str) -> list[tuple[str, str]]:
    """Parse `git status --porcelain=v1 -z --untracked-files=all` into (xy, rel_path) pairs."""
    items: list[tuple[str, str]] = []
    tokens = raw.split("\x00")
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok:
            i += 1
            continue
        xy = tok[:2]
        rel = tok[3:] if len(tok) >= 4 else ""
        items.append((xy, rel.replace("\\", "/")))
        # Rename/copy entries are followed by an extra NUL-separated source path.
        if xy and (xy[0] in ("R", "C") or xy[1] in ("R", "C")):
            i += 2
        else:
            i += 1
    return items


def _is_ignored_path(rel_path: str, prefixes: tuple[str, ...]) -> bool:
    norm = rel_path.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return any(norm.startswith(p) or norm == p.rstrip("/") for p in prefixes)


def list_dirty_files(cwd: Path, ignore_prefixes: tuple[str, ...] = (".agent/",)) -> list[str] | None:
    inside = _run_git(["rev-parse", "--is-inside-work-tree"], cwd)
    if not inside or inside.returncode != 0 or inside.stdout.strip() != "true":
        return None
    st = _run_git(["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd)
    if not st or st.returncode != 0:
        return None
    dirty: list[str] = []
    for _xy, rel in _parse_porcelain_z(st.stdout):
        if rel and not _is_ignored_path(rel, ignore_prefixes):
            dirty.append(rel)
    return sorted(set(dirty))


def git_tree_fingerprint(
    cwd: Path,
    ignore_prefixes: tuple[str, ...] = DEFAULT_AUDIT_IGNORE_PREFIXES,
) -> dict[str, Any] | None:
    """
    Build a tamper-resistant workspace fingerprint for read-only auditing.
    Captures HEAD SHA, staged diff digest, and status + content SHA256 for all
    modified/staged/untracked paths (excluding bridge-owned log prefixes).
    Returns None if git verification cannot be performed.
    """
    inside = _run_git(["rev-parse", "--is-inside-work-tree"], cwd)
    if not inside or inside.returncode != 0 or inside.stdout.strip() != "true":
        return None

    head_res = _run_git(["rev-parse", "--verify", "HEAD"], cwd)
    if head_res is None:
        return None
    if head_res.returncode == 0:
        head_sha = head_res.stdout.strip()
    else:
        # Distinguish unborn branch (empty repo) from genuine git errors.
        sym = _run_git(["symbolic-ref", "--quiet", "HEAD"], cwd)
        if sym is not None and sym.returncode == 0:
            head_sha = "(unborn)"
        else:
            return None

    st = _run_git(["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd)
    if not st or st.returncode != 0:
        return None

    cached = _run_git(["diff", "--cached", "--binary"], cwd, text=False)
    if not cached or cached.returncode != 0:
        return None
    staged_digest = hashlib.sha256(cached.stdout or b"").hexdigest()

    entries: list[tuple[str, str, str]] = []
    for xy, rel in _parse_porcelain_z(st.stdout):
        if not rel or _is_ignored_path(rel, ignore_prefixes):
            continue
        entries.append((xy, rel, _sha256_file(cwd / rel)))
    entries.sort()
    return {
        "head": head_sha,
        "staged_diff_sha256": staged_digest,
        "entries": entries,
    }


def _extract_error_text(err_obj: Any) -> str | None:
    if isinstance(err_obj, dict):
        code = str(err_obj.get("code") or "").strip()
        msg = str(err_obj.get("message") or err_obj.get("detail") or "").strip()
        if code and msg:
            return f"{code}: {msg}"
        return msg or code or json.dumps(err_obj, ensure_ascii=False)
    if isinstance(err_obj, str) and err_obj.strip():
        return err_obj.strip()
    if err_obj:
        return str(err_obj)
    return None


def parse_dsh_jsonl_detailed(raw_stdout: str) -> dict[str, Any]:
    session_id = None
    last_text = ""
    usage: dict[str, Any] = {}
    terminal_error: str | None = None
    saw_final = False
    event_count = 0

    for line in raw_stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        event_count += 1
        sid = ev.get("sessionId") or ev.get("session_id")
        if sid and not session_id:
            session_id = str(sid)
        if isinstance(ev.get("usage"), dict):
            usage = ev["usage"]

        ev_type = ev.get("type")
        if ev_type == "final":
            saw_final = True
            txt = ev.get("text")
            if isinstance(txt, str) and txt.strip():
                last_text = txt
            reason = ev.get("reason")
            if isinstance(reason, dict) and reason.get("kind") == "error":
                terminal_error = _extract_error_text(reason.get("error") or reason)
            elif ev.get("error"):
                terminal_error = _extract_error_text(ev.get("error"))
        elif ev_type == "error":
            terminal_error = _extract_error_text(ev.get("error") or ev.get("message") or ev)
        elif ev_type in ("assistant_message", "message"):
            txt = ev.get("text") or ev.get("content")
            if isinstance(txt, str) and txt.strip():
                last_text = txt

    return {
        "session_id": session_id,
        "reply": last_text.strip(),
        "usage": usage,
        "terminal_error": terminal_error,
        "saw_terminal_success": saw_final and terminal_error is None,
        "event_count": event_count,
    }


def parse_dsh_jsonl(raw_stdout: str) -> tuple[str | None, str, dict[str, Any], str | None]:
    d = parse_dsh_jsonl_detailed(raw_stdout)
    return d["session_id"], d["reply"], d["usage"], d["terminal_error"]


def parse_codex_jsonl_detailed(raw_stdout: str) -> dict[str, Any]:
    session_id = None
    last_text = ""
    usage: dict[str, Any] = {}
    terminal_error: str | None = None
    saw_completed = False
    event_count = 0

    for line in raw_stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        event_count += 1
        if ev.get("type") == "thread.started" and ev.get("thread_id"):
            session_id = str(ev["thread_id"])
        elif ev.get("thread_id") and not session_id:
            session_id = str(ev["thread_id"])

        ev_type = ev.get("type")
        if ev_type == "turn.completed":
            saw_completed = True
            if isinstance(ev.get("usage"), dict):
                usage = ev["usage"]
        elif ev_type in ("turn.failed", "error"):
            terminal_error = _extract_error_text(ev.get("error") or ev.get("message") or ev)

        item = ev.get("item")
        if isinstance(item, dict) and item.get("type") in ("agent_message", "assistant_message"):
            txt = item.get("text") or item.get("content")
            if isinstance(txt, str) and txt.strip():
                last_text = txt

    return {
        "session_id": session_id,
        "reply": last_text.strip(),
        "usage": usage,
        "terminal_error": terminal_error,
        "saw_terminal_success": saw_completed and terminal_error is None,
        "event_count": event_count,
    }


def parse_codex_jsonl(raw_stdout: str) -> tuple[str | None, str, dict[str, Any]]:
    d = parse_codex_jsonl_detailed(raw_stdout)
    return d["session_id"], d["reply"], d["usage"]


def extract_checker_verdict(reply: str) -> str | None:
    """
    Extract an explicit PASS or FAIL verdict from a Checker reply.
    Ignores prompt template echoes like "(PASS / FAIL)".
    """
    if not reply or not reply.strip():
        return None
    cleaned_lines: list[str] = []
    for raw_line in reply.splitlines():
        # Strip obvious template placeholders such as "PASS / FAIL" or "PASS/FAIL".
        line = re.sub(r"\bPASS\s*/\s*FAIL\b", "", raw_line, flags=re.IGNORECASE)
        cleaned_lines.append(line)

    # Pass 1: Explicit verdict-labelled lines (English or Chinese).
    label_re = re.compile(
        r"(?:verdict|spec\s+compliance|compliance|结论|裁决|判定|审查结果)"
        r"[^A-Za-z0-9\r\n]{0,20}"
        r"(?:\*{0,2}|`{0,1}|\[{0,1})\b(PASS|FAIL)\b",
        re.IGNORECASE,
    )
    for line in cleaned_lines:
        m = label_re.search(line)
        if m:
            return m.group(1).upper()

    # Pass 2: Standalone PASS/FAIL line (e.g. "1. **PASS**" or "FAIL").
    standalone_re = re.compile(
        r"^\s*(?:[-*]|\d+[.)])?\s*(?:\*{0,2}|`{0,1}|\[{0,1})\b(PASS|FAIL)\b(?:\*{0,2}|`{0,1}|\]{0,1})\s*[:：\-—.]?\s*$",
        re.IGNORECASE,
    )
    for line in cleaned_lines:
        m = standalone_re.match(line)
        if m:
            return m.group(1).upper()

    # Pass 3: Unambiguous single-token verdict anywhere in cleaned text.
    found = {m.group(1).upper() for m in re.finditer(r"\b(PASS|FAIL)\b", "\n".join(cleaned_lines))}
    if len(found) == 1:
        return next(iter(found))
    return None


def detect_infra_failure(*texts: str | None) -> bool:
    combined = "\n".join(t for t in texts if t).lower()
    return any(
        token in combined
        for token in (
            "429",
            "rate limit",
            "quota",
            "insufficient_quota",
            "billing",
            "timeout",
            "timed out",
            "temporarily unavailable",
            "overloaded",
            "connection reset",
        )
    )


def build_codex_cmd(
    codex_bin: str,
    spec: dict[str, Any],
    cwd: Path,
    last_msg_file: Path,
    session_id: str | None,
) -> list[str]:
    provider = spec.get("provider", "openai")
    tier = spec.get("service_tier", "default")
    effort = spec.get("effort", "high")
    readonly = bool(spec.get("readonly", False))
    sandbox_mode = str(spec.get("sandbox") or ("read-only" if readonly else "workspace-write"))

    base_overrides = [
        "-c", f'model_provider="{provider}"',
        "-c", f'service_tier="{tier}"',
        "-c", f'model_reasoning_effort="{effort}"',
        "-m", spec["model"],
    ]
    # IMPORTANT (verified on codex-cli 0.171.0):
    # `--sandbox` MUST appear on `codex exec` BEFORE the `resume` subcommand.
    if session_id:
        return [
            codex_bin,
            "exec",
            "--sandbox",
            sandbox_mode,
            "resume",
            session_id,
            "--json",
            "-o",
            str(last_msg_file),
            *base_overrides,
            "-",
        ]
    return [
        codex_bin,
        "exec",
        "--sandbox",
        sandbox_mode,
        "--json",
        "-C",
        str(cwd),
        "--skip-git-repo-check",
        "-o",
        str(last_msg_file),
        *base_overrides,
        "-",
    ]


def build_dsh_cmd(
    dsh_bin: str,
    spec: dict[str, Any],
    session_id: str | None,
) -> tuple[list[str], str]:
    readonly = bool(spec.get("readonly", False))
    perm = "read-only" if readonly else "workspace-write"
    cmd = [dsh_bin, "--profile", "headless"]
    patch_rel = spec.get("patch")
    if patch_rel:
        patch_path = Path(patch_rel)
        if not patch_path.is_absolute():
            patch_path = SCRIPT_DIR / patch_path
        cmd.extend(["--patch", str(patch_path)])
    cmd.extend(["--json", "--permission-mode", perm, "--approval-policy", "never"])
    if session_id:
        cmd.extend(["--session-id", session_id])
    cmd.append("-")
    return cmd, perm


def _terminate_process_tree(proc: subprocess.Popen[Any]) -> None:
    """Force-terminate the runner and all descendant processes (handles Windows .cmd wrappers)."""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except Exception:
            pass
    else:
        try:
            os.killpg(proc.pid, 9)
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def _run_process_to_files(
    cmd: list[str],
    prompt_text: str,
    cwd: Path,
    env: dict[str, str],
    raw_log: Path,
    err_log: Path,
    timeout: int,
) -> tuple[int, bool]:
    """
    Launch runner with stdout/stderr redirected directly to log files from t=0,
    so partial events and session_id survive timeouts.
    """
    with (
        tempfile.TemporaryFile(mode="w+b") as stdin_f,
        raw_log.open("wb") as out_f,
        err_log.open("wb") as err_f,
    ):
        stdin_f.write(prompt_text.encode("utf-8"))
        stdin_f.flush()
        stdin_f.seek(0)

        popen_kwargs: dict[str, Any] = {}
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(
            cmd,
            stdin=stdin_f,
            stdout=out_f,
            stderr=err_f,
            cwd=str(cwd),
            env=env,
            **popen_kwargs,
        )
        try:
            rc = proc.wait(timeout=timeout)
            return rc, False
        except subprocess.TimeoutExpired:
            _terminate_process_tree(proc)
            return 124, True


def run_smoke_test(roles: dict[str, dict[str, Any]]) -> int:
    dsh_bin = resolve_bin("DSH_BIN", "dsh")
    codex_bin = resolve_bin("CODEX_BIN", "codex")
    report: dict[str, Any] = {
        "roles_loaded": sorted(roles.keys()),
        "dsh": {},
        "codex": {},
    }

    if dsh_bin:
        ver = subprocess.run([dsh_bin, "--version"], capture_output=True, text=True, timeout=20)
        report["dsh"] = {
            "bin": dsh_bin,
            "version": (ver.stdout or ver.stderr).strip(),
            "ok": ver.returncode == 0,
        }
    else:
        report["dsh"] = {"ok": False, "hint": "Set DSH_BIN or add dsh to PATH"}

    if codex_bin:
        ver = subprocess.run([codex_bin, "--version"], capture_output=True, text=True, timeout=20)
        login = subprocess.run([codex_bin, "login", "status"], capture_output=True, text=True, timeout=20)
        report["codex"] = {
            "bin": codex_bin,
            "version": (ver.stdout or ver.stderr).strip(),
            "login": (login.stdout or login.stderr).strip(),
            "ok": ver.returncode == 0 and "Logged in" in (login.stdout + login.stderr),
        }
    else:
        report["codex"] = {"ok": False, "hint": "Set CODEX_BIN or add codex to PATH"}

    role_readiness: dict[str, bool] = {}
    for rname, rspec in sorted(roles.items()):
        runner = rspec.get("runner")
        if runner == "dsh":
            patch_ok = True
            patch_rel = rspec.get("patch")
            if patch_rel:
                p = Path(patch_rel)
                if not p.is_absolute():
                    p = SCRIPT_DIR / p
                patch_ok = p.exists()
            role_readiness[rname] = bool(report["dsh"].get("ok")) and patch_ok
        elif runner == "codex":
            role_readiness[rname] = bool(report["codex"].get("ok"))
        else:
            role_readiness[rname] = False

    report["role_readiness"] = role_readiness
    report["default_chain_ok"] = bool(role_readiness.get("builder")) and bool(role_readiness.get("checker"))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["default_chain_ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Portable hardened multi-agent CLI bridge")
    parser.add_argument("--config", help="Optional path to custom roles JSON file")
    parser.add_argument("--smoke-test", action="store_true", help="Verify runner availability and auth")
    parser.add_argument("--role", help="Target role name from roles config")
    parser.add_argument("--cwd", default=".", help="Workspace root directory")
    parser.add_argument("--prompt", help="Task prompt text")
    parser.add_argument("--prompt-file", help="Path to file containing task prompt")
    parser.add_argument("--session-id", help="Resume an existing runner session/thread id")
    parser.add_argument("--output-file", help="Optional path to write final reply")
    parser.add_argument("--timeout", type=int, help="Override timeout in seconds")
    args = parser.parse_args()

    roles = load_roles(Path(args.config) if args.config else None)
    if args.smoke_test:
        return run_smoke_test(roles)

    if not args.role or args.role not in roles:
        parser.error(f"--role must be one of: {', '.join(sorted(roles.keys()))}")

    prompt_text = args.prompt or ""
    if args.prompt_file:
        prompt_text = Path(args.prompt_file).read_text(encoding="utf-8")
    if not prompt_text.strip():
        parser.error("Provide --prompt or --prompt-file")

    spec = roles[args.role]
    cwd = Path(args.cwd).resolve()
    timeout = args.timeout or int(spec.get("timeout", 300))
    readonly = bool(spec.get("readonly", False))
    require_verdict = bool(spec.get("require_verdict", args.role in CHECKER_ROLES))

    logs_dir = (cwd / ".agent" / "logs").resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{ts}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    raw_log = logs_dir / f"{args.role}-{run_id}.jsonl"
    err_log = logs_dir / f"{args.role}-{run_id}.stderr.log"
    last_msg_file = logs_dir / f"{args.role}-{run_id}.last.md"

    guard = spec.get("system_guard", "").strip()
    full_prompt = f"{guard}\n\n---\n\n{prompt_text}" if guard else prompt_text

    before_fp = git_tree_fingerprint(cwd) if readonly else None
    pre_existing_dirty = list_dirty_files(cwd) if not readonly else None

    runner = spec["runner"]
    env = os.environ.copy()
    if runner == "dsh":
        dsh_bin = resolve_bin("DSH_BIN", "dsh")
        if not dsh_bin:
            print(json.dumps({"ok": False, "run_id": run_id, "error": "dsh binary not found (set DSH_BIN)"}, ensure_ascii=False))
            return 2
        cmd, perm = build_dsh_cmd(dsh_bin, spec, args.session_id)
        env["DSH_PERMISSION_MODE"] = perm
    elif runner == "codex":
        codex_bin = resolve_bin("CODEX_BIN", "codex")
        if not codex_bin:
            print(json.dumps({"ok": False, "run_id": run_id, "error": "codex binary not found (set CODEX_BIN)"}, ensure_ascii=False))
            return 2
        cmd = build_codex_cmd(codex_bin, spec, cwd, last_msg_file, args.session_id)
    else:
        print(json.dumps({"ok": False, "run_id": run_id, "error": f"Unsupported runner: {runner}"}, ensure_ascii=False))
        return 2

    rc, timed_out = _run_process_to_files(cmd, full_prompt, cwd, env, raw_log, err_log, timeout)
    raw_stdout = raw_log.read_text(encoding="utf-8", errors="replace") if raw_log.exists() else ""
    raw_stderr = err_log.read_text(encoding="utf-8", errors="replace") if err_log.exists() else ""

    if runner == "dsh":
        parsed = parse_dsh_jsonl_detailed(raw_stdout)
        reply = parsed["reply"]
        if not reply and parsed["terminal_error"]:
            reply = f"[DSH ERROR] {parsed['terminal_error']}"
        elif not reply and parsed["event_count"] == 0 and raw_stdout and not raw_stdout.lstrip().startswith("{"):
            reply = raw_stdout.strip()[-4000:]
    else:
        parsed = parse_codex_jsonl_detailed(raw_stdout)
        reply = parsed["reply"]
        if last_msg_file.exists():
            file_reply = last_msg_file.read_text(encoding="utf-8", errors="replace").strip()
            if file_reply:
                reply = file_reply

    session_id = parsed["session_id"]
    usage = parsed["usage"]
    terminal_error = parsed["terminal_error"]
    saw_terminal_success = parsed["saw_terminal_success"]
    event_count = parsed["event_count"]

    readonly_violation = False
    if not readonly:
        readonly_audit = "not_applicable"
    elif before_fp is None:
        readonly_audit = "unverified"
    else:
        after_fp = git_tree_fingerprint(cwd)
        if after_fp is None:
            readonly_audit = "unverified"
        elif after_fp != before_fp:
            readonly_violation = True
            readonly_audit = "violated"
        else:
            readonly_audit = "clean"

    checker_verdict: str | None = extract_checker_verdict(reply) if require_verdict else None

    errors: list[str] = []
    if timed_out:
        errors.append(f"timeout after {timeout}s")
    if rc != 0 and not timed_out:
        errors.append(f"runner exited with code {rc}")
    if terminal_error:
        errors.append(f"terminal error: {terminal_error}")
    if readonly_violation:
        errors.append("read-only workspace audit violation detected")
    if not timed_out and event_count > 0 and not saw_terminal_success and not terminal_error:
        errors.append("runner stream ended without terminal completion event")
    if not timed_out and not reply.strip() and not terminal_error:
        errors.append("runner produced empty reply")
    if not errors and require_verdict and checker_verdict is None:
        errors.append("checker reply missing explicit PASS/FAIL verdict")

    infra_failure = timed_out or detect_infra_failure(raw_stderr, terminal_error)
    ok = len(errors) == 0

    if args.output_file and reply:
        out_p = Path(args.output_file)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(reply, encoding="utf-8")

    summary: dict[str, Any] = {
        "ok": ok,
        "run_id": run_id,
        "role": args.role,
        "runner": runner,
        "model": spec.get("model") or spec.get("model_label"),
        "exit_code": rc,
        "session_id": session_id,
        "usage": usage,
        "infra_failure": infra_failure,
        "readonly_violation": readonly_violation,
        "readonly_audit": readonly_audit,
        "error": "; ".join(errors) if errors else None,
        "raw_log": str(raw_log),
        "stderr_log": str(err_log),
        "output_file": args.output_file,
        "reply": reply,
    }
    if require_verdict:
        summary["checker_verdict"] = checker_verdict
    if pre_existing_dirty is not None:
        summary["pre_existing_dirty"] = pre_existing_dirty

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if timed_out:
        return 124
    return 0 if ok else (rc if rc != 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
