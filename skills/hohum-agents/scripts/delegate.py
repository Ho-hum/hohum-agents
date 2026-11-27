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
CHECKER_ROLES = {"checker"}
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


def _provider_family(spec: dict[str, Any]) -> str:
    runner = str(spec.get("runner") or "").strip().lower()
    provider = str(spec.get("provider") or "").strip().lower()
    model = str(spec.get("model") or spec.get("model_label") or "").strip().lower()
    if provider:
        return provider
    if "gemini" in model:
        return "google"
    if "deepseek" in model or runner == "dsh":
        return "deepseek"
    if "gpt" in model or "o1" in model or "o3" in model or runner == "codex":
        return "openai"
    if runner == "host":
        return "host"
    return runner or "unknown"


def _detect_esbuild_ready(cwd: Path) -> bool:
    candidates = [
        cwd / "node_modules" / "esbuild" / "package.json",
        cwd / "node_modules" / ".bin" / "esbuild",
        cwd / "node_modules" / ".bin" / "esbuild.cmd",
    ]
    return any(p.exists() for p in candidates)


def _extract_probe_json(reply: str) -> dict[str, Any] | None:
    if not reply or not reply.strip():
        return None
    text = reply.strip()
    # Try direct JSON first, then fenced JSON block, then last {...} object.
    candidates: list[str] = [text]
    for m in re.finditer(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE):
        candidates.append(m.group(1))
    brace_matches = list(re.finditer(r"\{[^{}]*\}", text, flags=re.DOTALL))
    if brace_matches:
        candidates.append(brace_matches[-1].group(0))
    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _select_probe_roles(
    roles: dict[str, dict[str, Any]],
    requested: str | None,
) -> list[str]:
    if requested:
        picked = [r.strip() for r in requested.split(",") if r.strip() in roles]
        return picked
    selected: list[str] = []
    # Preferred canonical write roles & read-only review roles first.
    preferred = ["builder", "builder-escalation", "checker"]
    for name in preferred:
        if name in roles and name not in selected:
            selected.append(name)
    # Ensure every distinct external (runner, readonly) pair is represented at least once.
    covered = {(roles[r].get("runner"), bool(roles[r].get("readonly", False))) for r in selected}
    for name, spec in sorted(roles.items()):
        if spec.get("runner") == "host":
            continue
        key = (spec.get("runner"), bool(spec.get("readonly", False)))
        if key not in covered:
            selected.append(name)
            covered.add(key)
    return selected


def _probe_single_role(
    role_name: str,
    spec: dict[str, Any],
    cwd: Path,
    esbuild_ready: bool,
    timeout: int = 120,
) -> dict[str, Any]:
    runner = spec.get("runner")
    readonly = bool(spec.get("readonly", False))
    logs_dir = (cwd / ".agent" / "logs").resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"probe-{ts}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    raw_log = logs_dir / f"{role_name}-{run_id}.jsonl"
    err_log = logs_dir / f"{role_name}-{run_id}.stderr.log"
    last_msg_file = logs_dir / f"{role_name}-{run_id}.last.md"
    probe_rel = f".agent/logs/.smoke-probe-{run_id}.tmp"
    probe_file = cwd / probe_rel

    if readonly:
        probe_prompt = (
            "You are running a minimal read-only sandbox capability probe. "
            "Do NOT modify, create, or delete any file.\n"
            "1. Verify you can run a simple read-only shell command (echo SHELL_OK) or read workspace files.\n"
            "2. Reply with ONLY a single-line JSON object (no prose): "
            '{"read_ok": true, "shell_ok": <bool>, "detail": "<short reason>"}'
        )
    else:
        esbuild_step = (
            "3. Run via shell: node -e \"const p=require.resolve('esbuild',{paths:[process.cwd()]});"
            "const r=require(p).transformSync('const x:number=1',{loader:'ts'});console.log(r.code.trim())\" "
            "and record whether it succeeded as esbuild_ok (true/false).\n"
            if esbuild_ready
            else "3. esbuild is not installed in node_modules; set esbuild_ok to null without running esbuild.\n"
        )
        probe_prompt = (
            "You are running a minimal sandbox capability probe. Follow these steps strictly:\n"
            f"1. Create temporary file `{probe_rel}` containing `probe-ok`, verify it exists, then delete it immediately.\n"
            "2. Run a minimal command in your default shell that prints `SHELL_OK`.\n"
            f"{esbuild_step}"
            "4. Reply with ONLY a single-line JSON object (no markdown prose): "
            '{"write_ok": <bool>, "shell_ok": <bool>, "esbuild_ok": <bool|null>, "detail": "<short error or ok>"}'
        )

    before_fp = git_tree_fingerprint(cwd) if readonly else None
    env = os.environ.copy()
    if runner == "dsh":
        dsh_bin = resolve_bin("DSH_BIN", "dsh")
        if not dsh_bin:
            return {"ok": False, "readonly": readonly, "error": "dsh binary not found"}
        cmd, perm = build_dsh_cmd(dsh_bin, spec, None)
        env["DSH_PERMISSION_MODE"] = perm
    elif runner == "codex":
        codex_bin = resolve_bin("CODEX_BIN", "codex")
        if not codex_bin:
            return {"ok": False, "readonly": readonly, "error": "codex binary not found"}
        cmd = build_codex_cmd(codex_bin, spec, cwd, last_msg_file, None)
    else:
        return {"ok": False, "readonly": readonly, "error": f"unsupported runner: {runner}"}

    try:
        rc, timed_out = _run_process_to_files(cmd, probe_prompt, cwd, env, raw_log, err_log, timeout)
    finally:
        if probe_file.exists():
            try:
                probe_file.unlink()
            except OSError:
                pass

    raw_stdout = raw_log.read_text(encoding="utf-8", errors="replace") if raw_log.exists() else ""
    raw_stderr = err_log.read_text(encoding="utf-8", errors="replace") if err_log.exists() else ""
    if runner == "dsh":
        parsed = parse_dsh_jsonl_detailed(raw_stdout)
        reply = parsed["reply"]
    else:
        parsed = parse_codex_jsonl_detailed(raw_stdout)
        reply = parsed["reply"]
        if last_msg_file.exists():
            file_reply = last_msg_file.read_text(encoding="utf-8", errors="replace").strip()
            if file_reply:
                reply = file_reply

    readonly_violation = False
    if readonly and before_fp is not None:
        after_fp = git_tree_fingerprint(cwd)
        readonly_violation = after_fp is not None and after_fp != before_fp

    probe_obj = _extract_probe_json(reply)
    infra_failure = timed_out or detect_infra_failure(raw_stderr, parsed["terminal_error"])
    err_msg = None
    if timed_out:
        err_msg = f"timeout after {timeout}s"
    elif parsed["terminal_error"]:
        err_msg = parsed["terminal_error"]
    elif rc != 0:
        err_msg = f"runner exited with code {rc}"
    elif readonly_violation:
        err_msg = "read-only audit violation during probe"
    elif probe_obj is None:
        err_msg = "probe reply missing structured JSON"

    if readonly:
        read_ok = bool(probe_obj.get("read_ok")) if probe_obj else False
        shell_ok = bool(probe_obj.get("shell_ok")) if probe_obj else False
        role_ok = (err_msg is None) and read_ok and not readonly_violation
        return {
            "ok": role_ok,
            "runner": runner,
            "provider_family": _provider_family(spec),
            "readonly": True,
            "read_ok": read_ok,
            "shell_ok": shell_ok,
            "infra_failure": infra_failure,
            "detail": (probe_obj or {}).get("detail") or err_msg or "ok",
            "error": err_msg,
            "raw_log": str(raw_log),
        }

    write_ok = bool(probe_obj.get("write_ok")) if probe_obj else False
    shell_ok = bool(probe_obj.get("shell_ok")) if probe_obj else False
    esbuild_ok: bool | None = None
    if probe_obj is not None and "esbuild_ok" in probe_obj:
        val = probe_obj.get("esbuild_ok")
        esbuild_ok = bool(val) if isinstance(val, bool) else None
    elif not esbuild_ready:
        esbuild_ok = None

    # A coder role can still edit code & run static checks even if esbuild spawn fails in sandbox.
    coder_usable = (err_msg is None) and write_ok and shell_ok
    return {
        "ok": coder_usable,
        "runner": runner,
        "provider_family": _provider_family(spec),
        "readonly": False,
        "write_ok": write_ok,
        "shell_ok": shell_ok,
        "esbuild_ok": esbuild_ok if esbuild_ready else "skipped_not_installed",
        "infra_failure": infra_failure,
        "detail": (probe_obj or {}).get("detail") or err_msg or "ok",
        "error": err_msg,
        "raw_log": str(raw_log),
    }


def _build_configured_roles_and_advice(
    roles: dict[str, dict[str, Any]],
    role_readiness: dict[str, bool],
    sandbox_probes: dict[str, dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # Map (runner, readonly) -> probe result so unprobed roles sharing the same sandbox inherit the finding.
    sandbox_by_key: dict[tuple[Any, bool], dict[str, Any]] = {}
    if sandbox_probes:
        for pname, pres in sandbox_probes.items():
            if pname in roles and not pres.get("skipped"):
                pkey = (roles[pname].get("runner"), bool(roles[pname].get("readonly", False)))
                sandbox_by_key.setdefault(pkey, pres)

    def get_probe(name: str) -> dict[str, Any] | None:
        if not sandbox_probes:
            return None
        if name in sandbox_probes:
            return sandbox_probes[name]
        if name in roles:
            pkey = (roles[name].get("runner"), bool(roles[name].get("readonly", False)))
            return sandbox_by_key.get(pkey)
        return None

    def is_role_usable(name: str) -> bool:
        if not role_readiness.get(name):
            return False
        probe = get_probe(name)
        if probe is not None:
            return bool(probe.get("ok"))
        return True

    canonical_order = [
        "scout",
        "builder",
        "builder-mech",
        "checker",
        "tech-advisor",
        "design-advisor",
        "builder-escalation",
    ]
    ordered_all = [r for r in canonical_order if r in roles] + [
        r for r in sorted(roles.keys()) if r not in canonical_order
    ]

    configured_roles: list[dict[str, Any]] = []
    failed_roles: list[dict[str, Any]] = []
    for rname in ordered_all:
        spec = roles[rname]
        probe = get_probe(rname)
        entry: dict[str, Any] = {
            "role": rname,
            "runner": spec.get("runner"),
            "model": spec.get("model") or spec.get("model_label") or "(unspecified)",
            "provider_family": _provider_family(spec),
            "readonly": bool(spec.get("readonly", False)),
            "ready": bool(role_readiness.get(rname)),
        }
        if probe is not None:
            entry["sandbox_probe_ok"] = bool(probe.get("ok"))
            if "esbuild_ok" in probe:
                entry["esbuild_ok"] = probe.get("esbuild_ok")
            entry["detail"] = probe.get("detail") or probe.get("error") or "ok"
            if not probe.get("ok"):
                failed_roles.append(
                    {
                        "role": rname,
                        "model": entry["model"],
                        "runner": entry["runner"],
                        "reason": entry["detail"],
                    }
                )
        elif not entry["ready"]:
            failed_roles.append(
                {
                    "role": rname,
                    "model": entry["model"],
                    "runner": entry["runner"],
                    "reason": "runner CLI, auth, or patch check failed",
                }
            )
        configured_roles.append(entry)

    usable_coders = [
        r for r in ordered_all
        if not bool(roles[r].get("readonly", False)) and is_role_usable(r)
    ] + ["host-self"]
    usable_reviewers = [
        r for r in ordered_all
        if bool(roles[r].get("readonly", False)) and is_role_usable(r)
    ]

    suggestions: list[str] = []
    builder_ok = "builder" in roles and is_role_usable("builder")
    checker_ok = "checker" in roles and is_role_usable("checker")
    esbuild_partial_roles = [
        e["role"] for e in configured_roles if e.get("sandbox_probe_ok") and e.get("esbuild_ok") is False
    ]

    if not builder_ok and "builder" in roles:
        suggestions.append(
            f"Default 'builder' cannot run cleanly. Pause and ask human to choose: "
            f"(a) fix/wait for default builder, or (b) switch coder to one of {usable_coders} "
            f"and confirm a cross-provider independent reviewer from {usable_reviewers}."
        )
    if not checker_ok and "checker" in roles:
        suggestions.append(
            f"Default 'checker' cannot run cleanly. Pause and ask human to choose: "
            f"(a) wait/fix default checker, or (b) explicitly designate a cross-provider reviewer from {usable_reviewers}."
        )
    if esbuild_partial_roles:
        suggestions.append(
            f"Roles {esbuild_partial_roles} can write files and run static checks in sandbox, but esbuild spawn failed; "
            "propose offloading only esbuild-dependent commands (e.g. vitest/build) to host while keeping sandbox static checks."
        )
    if not suggestions:
        suggestions.append(
            "Default builder and checker are ready. Present `configured_roles` to human for confirmation before Slice 1."
        )

    advice: dict[str, Any] = {
        "auto_switch": False,
        "human_decision_required": (not builder_ok) or (not checker_ok) or bool(failed_roles) or bool(esbuild_partial_roles),
        "failed_roles": failed_roles,
        "usable_coders": usable_coders,
        "usable_reviewers": usable_reviewers,
        "suggestions": suggestions,
    }
    return configured_roles, advice


def run_smoke_test(
    roles: dict[str, dict[str, Any]],
    cwd: Path | None = None,
    probe_sandboxes: bool = False,
    probe_roles_arg: str | None = None,
    probe_timeout: int = 120,
) -> int:
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
        elif runner == "host":
            role_readiness[rname] = True
        else:
            role_readiness[rname] = False

    report["role_readiness"] = role_readiness

    sandbox_probes: dict[str, dict[str, Any]] | None = None
    if probe_sandboxes:
        target_cwd = (cwd or Path(".")).resolve()
        esbuild_ready = _detect_esbuild_ready(target_cwd)
        report["probe_context"] = {
            "cwd": str(target_cwd),
            "esbuild_installed": esbuild_ready,
        }
        sandbox_probes = {}
        for rname in _select_probe_roles(roles, probe_roles_arg):
            if not role_readiness.get(rname):
                sandbox_probes[rname] = {
                    "ok": False,
                    "skipped": True,
                    "error": "runner or patch failed basic smoke check",
                }
                continue
            sandbox_probes[rname] = _probe_single_role(
                rname, roles[rname], target_cwd, esbuild_ready, timeout=probe_timeout
            )
        report["sandbox_probes"] = sandbox_probes

    configured_roles, advice = _build_configured_roles_and_advice(roles, role_readiness, sandbox_probes)
    report["configured_roles"] = configured_roles
    report["decision_advice"] = advice
    if probe_sandboxes:
        default_builder_ok = bool(sandbox_probes and sandbox_probes.get("builder", {}).get("ok"))
        default_checker_ok = bool(sandbox_probes and sandbox_probes.get("checker", {}).get("ok"))
        report["default_chain_ok"] = default_builder_ok and default_checker_ok
    else:
        report["default_chain_ok"] = bool(role_readiness.get("builder")) and bool(role_readiness.get("checker"))
        report["probe_hint"] = "Pass --probe-sandboxes --cwd <repo> to verify temp write, shell, and esbuild in target sandboxes."

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["default_chain_ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Portable hardened multi-agent CLI bridge")
    parser.add_argument("--config", help="Optional path to custom roles JSON file")
    parser.add_argument("--smoke-test", action="store_true", help="Verify runner availability and auth")
    parser.add_argument(
        "--probe-sandboxes",
        action="store_true",
        help="With --smoke-test: execute live sandbox probes (temp write, shell, esbuild if installed) and print recommended routing",
    )
    parser.add_argument(
        "--probe-roles",
        help="With --probe-sandboxes: comma-separated role names to probe (default: primary write & review roles)",
    )
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
        return run_smoke_test(
            roles,
            cwd=Path(args.cwd),
            probe_sandboxes=args.probe_sandboxes or bool(args.probe_roles),
            probe_roles_arg=args.probe_roles,
            probe_timeout=args.timeout or 120,
        )

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
    elif runner == "host":
        print(
            json.dumps(
                {
                    "ok": False,
                    "run_id": run_id,
                    "error": f"Role '{args.role}' uses runner='host'; invoke it via a host-native subagent (or switch runner to 'codex'/'dsh' in roles.local.json).",
                },
                ensure_ascii=False,
            )
        )
        return 2
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
