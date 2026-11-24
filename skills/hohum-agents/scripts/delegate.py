#!/usr/bin/env python3
"""
Portable hardened CLI bridge for hohum-agents.
Loads role definitions from roles.local.json (git-ignored) if present,
falling back to roles.example.json. Zero third-party dependencies (Python 3.10+).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent


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


def git_status_snapshot(cwd: Path) -> str | None:
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if res.returncode == 0:
            return res.stdout
    except Exception:
        pass
    return None


def parse_dsh_jsonl(raw_stdout: str) -> tuple[str | None, str, dict[str, Any], str | None]:
    session_id = None
    last_text = ""
    usage: dict[str, Any] = {}
    err_msg: str | None = None
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
        sid = ev.get("sessionId") or ev.get("session_id")
        if sid and not session_id:
            session_id = str(sid)
        if isinstance(ev.get("usage"), dict):
            usage = ev["usage"]
        ev_type = ev.get("type")
        if ev_type == "final":
            txt = ev.get("text")
            if isinstance(txt, str) and txt.strip():
                last_text = txt
            reason = ev.get("reason")
            if isinstance(reason, dict) and reason.get("kind") == "error":
                err_obj = reason.get("error")
                if isinstance(err_obj, dict):
                    err_msg = f"{err_obj.get('code', 'ERROR')}: {err_obj.get('message', '')}".strip()
                elif err_obj:
                    err_msg = str(err_obj)
        elif ev_type in ("assistant_message", "message"):
            txt = ev.get("text") or ev.get("content")
            if isinstance(txt, str) and txt.strip():
                last_text = txt
    return session_id, last_text.strip(), usage, err_msg


def parse_codex_jsonl(raw_stdout: str) -> tuple[str | None, str, dict[str, Any]]:
    session_id = None
    last_text = ""
    usage: dict[str, Any] = {}
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
        if ev.get("type") == "thread.started" and ev.get("thread_id"):
            session_id = str(ev["thread_id"])
        elif ev.get("thread_id") and not session_id:
            session_id = str(ev["thread_id"])
        if ev.get("type") == "turn.completed" and isinstance(ev.get("usage"), dict):
            usage = ev["usage"]
        item = ev.get("item")
        if isinstance(item, dict) and item.get("type") in ("agent_message", "assistant_message"):
            txt = item.get("text") or item.get("content")
            if isinstance(txt, str) and txt.strip():
                last_text = txt
    return session_id, last_text.strip(), usage


def detect_infra_failure(stderr_text: str) -> bool:
    low = (stderr_text or "").lower()
    return any(
        token in low
        for token in (
            "429",
            "rate limit",
            "quota",
            "insufficient_quota",
            "billing",
            "timeout",
            "temporarily unavailable",
        )
    )


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

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if (report["dsh"].get("ok") or report["codex"].get("ok")) else 1


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

    logs_dir = cwd / ".agent" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    raw_log = logs_dir / f"{args.role}-{ts}.jsonl"
    err_log = logs_dir / f"{args.role}-{ts}.stderr.log"
    last_msg_file = logs_dir / f"{args.role}-{ts}.last.md"

    guard = spec.get("system_guard", "").strip()
    full_prompt = f"{guard}\n\n---\n\n{prompt_text}" if guard else prompt_text
    before_git = git_status_snapshot(cwd) if readonly else None

    runner = spec["runner"]
    if runner == "dsh":
        dsh_bin = resolve_bin("DSH_BIN", "dsh")
        if not dsh_bin:
            print(json.dumps({"ok": False, "error": "dsh binary not found (set DSH_BIN)"}, ensure_ascii=False))
            return 2
        perm = "read-only" if readonly else "workspace-write"
        cmd = [dsh_bin, "--profile", "headless"]
        patch_rel = spec.get("patch")
        if patch_rel:
            patch_path = Path(patch_rel)
            if not patch_path.is_absolute():
                patch_path = SCRIPT_DIR / patch_path
            cmd.extend(["--patch", str(patch_path)])
        cmd.extend(["--json", "--permission-mode", perm, "--approval-policy", "never"])
        if args.session_id:
            cmd.extend(["--session-id", args.session_id])
        cmd.append("-")
        env = os.environ.copy()
        env["DSH_PERMISSION_MODE"] = perm
        try:
            proc = subprocess.run(
                cmd,
                input=full_prompt,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            print(json.dumps({"ok": False, "role": args.role, "error": f"timeout after {timeout}s", "infra_failure": True}, ensure_ascii=False))
            return 124
        raw_log.write_text(proc.stdout or "", encoding="utf-8")
        err_log.write_text(proc.stderr or "", encoding="utf-8")
        session_id, reply, usage, dsh_error = parse_dsh_jsonl(proc.stdout or "")
        if not reply and dsh_error:
            reply = f"[DSH ERROR] {dsh_error}"
        elif not reply and proc.stdout and not proc.stdout.lstrip().startswith("{"):
            reply = proc.stdout.strip()[-4000:]
    elif runner == "codex":
        codex_bin = resolve_bin("CODEX_BIN", "codex")
        if not codex_bin:
            print(json.dumps({"ok": False, "error": "codex binary not found (set CODEX_BIN)"}, ensure_ascii=False))
            return 2
        provider = spec.get("provider", "openai")
        tier = spec.get("service_tier", "default")
        effort = spec.get("effort", "high")
        base_overrides = [
            "-c", f'model_provider="{provider}"',
            "-c", f'service_tier="{tier}"',
            "-c", f'model_reasoning_effort="{effort}"',
            "-m", spec["model"],
        ]
        if args.session_id:
            cmd = [codex_bin, "exec", "resume", args.session_id, "--json", "-o", str(last_msg_file), *base_overrides, "-"]
        else:
            cmd = [codex_bin, "exec", "--json", "-C", str(cwd), "--skip-git-repo-check", "-o", str(last_msg_file), *base_overrides, "-"]
        try:
            proc = subprocess.run(
                cmd,
                input=full_prompt,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            print(json.dumps({"ok": False, "role": args.role, "error": f"timeout after {timeout}s", "infra_failure": True}, ensure_ascii=False))
            return 124
        raw_log.write_text(proc.stdout or "", encoding="utf-8")
        err_log.write_text(proc.stderr or "", encoding="utf-8")
        session_id, reply, usage = parse_codex_jsonl(proc.stdout or "")
        if last_msg_file.exists():
            file_reply = last_msg_file.read_text(encoding="utf-8", errors="replace").strip()
            if file_reply:
                reply = file_reply
    else:
        print(json.dumps({"ok": False, "error": f"Unsupported runner: {runner}"}, ensure_ascii=False))
        return 2

    readonly_violation = False
    if readonly and before_git is not None:
        after_git = git_status_snapshot(cwd)
        if after_git is not None and after_git != before_git:
            readonly_violation = True

    if args.output_file and reply:
        out_p = Path(args.output_file)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(reply, encoding="utf-8")

    summary = {
        "ok": proc.returncode == 0 and not readonly_violation,
        "role": args.role,
        "runner": runner,
        "model": spec.get("model") or spec.get("model_label"),
        "exit_code": proc.returncode,
        "session_id": session_id,
        "usage": usage,
        "infra_failure": detect_infra_failure(proc.stderr or ""),
        "readonly_violation": readonly_violation,
        "raw_log": str(raw_log),
        "stderr_log": str(err_log),
        "output_file": args.output_file,
        "reply": reply,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else (proc.returncode or 1)


if __name__ == "__main__":
    sys.exit(main())
