from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "skills" / "hohum-agents" / "scripts"
DELEGATE_PY = SCRIPTS_DIR / "delegate.py"
PACK_DIFF_PY = SCRIPTS_DIR / "pack_diff.py"


def load_module(name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(name, str(file_path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


delegate = load_module("delegate", DELEGATE_PY)


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr}")
    return res.stdout.strip()


def _init_repo(repo: Path) -> str:
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / ".gitignore").write_text(".agent/\n", encoding="utf-8")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "app.py")
    _git(repo, "commit", "-m", "initial commit")
    return _git(repo, "rev-parse", "HEAD")


def _make_fake_runner(tmp: Path, name: str, py_body: str) -> Path:
    stub_py = tmp / f"{name}_stub.py"
    stub_py.write_text(py_body, encoding="utf-8")
    if os.name == "nt":
        wrapper = tmp / f"{name}.cmd"
        wrapper.write_text(f'@echo off\r\n"{sys.executable}" "{stub_py}" %*\r\n', encoding="utf-8")
    else:
        wrapper = tmp / name
        wrapper.write_text(f'#!/usr/bin/env sh\nexec "{sys.executable}" "{stub_py}" "$@"\n', encoding="utf-8")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    return wrapper


def _run_delegate(
    repo: Path,
    role: str,
    prompt: str = "test task",
    env_extra: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
) -> tuple[int, dict]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    cmd = [
        sys.executable,
        str(DELEGATE_PY),
        "--config",
        str(SCRIPTS_DIR / "roles.example.json"),
        "--role",
        role,
        "--cwd",
        str(repo),
        "--prompt",
        prompt,
        *(extra_args or []),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
    data = json.loads(res.stdout)
    return res.returncode, data


class TestDelegateParsersAndConfig(unittest.TestCase):
    def test_load_example_roles(self) -> None:
        roles = delegate.load_roles(SCRIPTS_DIR / "roles.example.json")
        for expected in ("scout", "builder", "builder-mech", "checker", "tech-advisor", "design-advisor", "builder-escalation"):
            self.assertIn(expected, roles)
        self.assertNotIn("checker-fallback", roles)
        self.assertTrue(roles["scout"]["readonly"])
        self.assertTrue(roles["checker"]["readonly"])
        self.assertTrue(roles["design-advisor"]["readonly"])
        self.assertEqual(roles["design-advisor"]["runner"], "host")
        self.assertFalse(roles["builder"]["readonly"])

    def test_configured_roles_and_no_auto_switch_advice(self) -> None:
        roles = delegate.load_roles(SCRIPTS_DIR / "roles.example.json")
        ready = {k: True for k in roles}
        probes = {
            "builder": {"ok": False, "write_ok": True, "shell_ok": False, "esbuild_ok": None, "detail": "pwsh 0xC0000142"},
            "builder-escalation": {"ok": True, "write_ok": True, "shell_ok": True, "esbuild_ok": False, "detail": "esbuild EPERM"},
            "checker": {"ok": True, "read_ok": True, "shell_ok": True, "detail": "ok"},
            "scout": {"ok": True, "read_ok": True, "shell_ok": False, "detail": "read ok"},
        }
        configured, advice = delegate._build_configured_roles_and_advice(roles, ready, probes)
        self.assertEqual(len(configured), 7)
        self.assertFalse(advice["auto_switch"])
        self.assertTrue(advice["human_decision_required"])
        failed_names = {f["role"] for f in advice["failed_roles"]}
        self.assertIn("builder", failed_names)
        self.assertIn("builder-mech", failed_names)
        self.assertNotIn("builder-mech", advice["usable_coders"])
        self.assertIn("design-advisor", advice["usable_reviewers"])
        self.assertNotIn("design-advisor", delegate._select_probe_roles(roles, None))
        self.assertTrue(any("Pause and ask human" in s for s in advice["suggestions"]))
        self.assertTrue(any("esbuild" in s for s in advice["suggestions"]))

    def test_parse_dsh_jsonl_success(self) -> None:
        sample = "\n".join(
            [
                json.dumps({"type": "session", "sessionId": "session-123"}),
                json.dumps(
                    {
                        "type": "final",
                        "sessionId": "session-123",
                        "usage": {"inputTokens": 100, "outputTokens": 12},
                        "text": "SCOUT_OK",
                    }
                ),
            ]
        )
        sid, reply, usage, err = delegate.parse_dsh_jsonl(sample)
        self.assertEqual(sid, "session-123")
        self.assertEqual(reply, "SCOUT_OK")
        self.assertEqual(usage["inputTokens"], 100)
        self.assertIsNone(err)

    def test_parse_dsh_jsonl_error(self) -> None:
        sample = json.dumps(
            {
                "type": "final",
                "sessionId": "session-err",
                "reason": {"kind": "error", "error": {"code": "RATE_LIMIT", "message": "429 too many requests"}},
                "text": "",
            }
        )
        sid, reply, _, err = delegate.parse_dsh_jsonl(sample)
        self.assertEqual(sid, "session-err")
        self.assertEqual(reply, "")
        self.assertIn("RATE_LIMIT", err or "")

    def test_parse_codex_jsonl(self) -> None:
        sample = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "thr-456"}),
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "CHECKER_OK"}}),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 500, "cached_input_tokens": 400}}),
            ]
        )
        sid, reply, usage = delegate.parse_codex_jsonl(sample)
        self.assertEqual(sid, "thr-456")
        self.assertEqual(reply, "CHECKER_OK")
        self.assertEqual(usage["cached_input_tokens"], 400)

    def test_detect_infra_failure(self) -> None:
        self.assertTrue(delegate.detect_infra_failure("HTTP 429 rate limit exceeded"))
        self.assertTrue(delegate.detect_infra_failure("insufficient_quota"))
        self.assertFalse(delegate.detect_infra_failure("syntax error on line 10"))


class TestCodexSandboxAndResumeArgs(unittest.TestCase):
    def test_sandbox_flag_placement_initial_and_resume(self) -> None:
        roles = delegate.load_roles(SCRIPTS_DIR / "roles.example.json")
        cwd = Path(".").resolve()
        last_msg = cwd / "last.md"

        c_init = delegate.build_codex_cmd("codex", roles["checker"], cwd, last_msg, None)
        self.assertEqual(c_init[1:4], ["exec", "--sandbox", "read-only"])

        c_res = delegate.build_codex_cmd("codex", roles["checker"], cwd, last_msg, "thread-123")
        self.assertEqual(c_res[1:6], ["exec", "--sandbox", "read-only", "resume", "thread-123"])
        self.assertLess(c_res.index("--sandbox"), c_res.index("resume"))

        b_init = delegate.build_codex_cmd("codex", roles["builder-escalation"], cwd, last_msg, None)
        self.assertEqual(b_init[1:4], ["exec", "--sandbox", "workspace-write"])

        b_res = delegate.build_codex_cmd("codex", roles["builder-escalation"], cwd, last_msg, "thread-456")
        self.assertEqual(b_res[1:6], ["exec", "--sandbox", "workspace-write", "resume", "thread-456"])


class TestDelegateTerminalStatusAndVerdicts(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_obj.name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.base_sha = _init_repo(self.repo)

    def tearDown(self) -> None:
        self.tmp_obj.cleanup()

    def test_codex_empty_output_rc0_is_failure(self) -> None:
        fake = _make_fake_runner(
            self.tmp,
            "fake_codex_empty",
            "import sys\n_ = sys.stdin.read()\nsys.exit(0)\n",
        )
        rc, out = _run_delegate(self.repo, "checker", env_extra={"CODEX_BIN": str(fake)})
        self.assertNotEqual(rc, 0)
        self.assertFalse(out["ok"])
        self.assertIn("empty reply", out["error"])

    def test_codex_turn_failed_rc0_is_failure(self) -> None:
        fake = _make_fake_runner(
            self.tmp,
            "fake_codex_fail",
            """
import json, sys
_ = sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": "th-fail-1"}))
print(json.dumps({"type": "turn.failed", "error": {"message": "429 rate limit exceeded"}}))
sys.exit(0)
""",
        )
        rc, out = _run_delegate(self.repo, "checker", env_extra={"CODEX_BIN": str(fake)})
        self.assertNotEqual(rc, 0)
        self.assertFalse(out["ok"])
        self.assertTrue(out["infra_failure"])
        self.assertEqual(out["session_id"], "th-fail-1")
        self.assertIn("429", out["error"])

    def test_dsh_terminal_429_rc0_is_infra_failure(self) -> None:
        fake = _make_fake_runner(
            self.tmp,
            "fake_dsh_429",
            """
import json, sys
_ = sys.stdin.read()
print(json.dumps({
    "type": "final",
    "sessionId": "dsh-sess-429",
    "reason": {"kind": "error", "error": {"code": "429", "message": "limited"}}
}))
sys.exit(0)
""",
        )
        rc, out = _run_delegate(self.repo, "builder", env_extra={"DSH_BIN": str(fake)})
        self.assertNotEqual(rc, 0)
        self.assertFalse(out["ok"])
        self.assertTrue(out["infra_failure"])
        self.assertEqual(out["session_id"], "dsh-sess-429")
        self.assertIn("429", out["error"])

    def test_checker_distinguishes_valid_fail_from_missing_verdict(self) -> None:
        fake_fail_verdict = _make_fake_runner(
            self.tmp,
            "fake_codex_verdict_fail",
            """
import json, sys
_ = sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": "th-v1"}))
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "1. Spec compliance verdict: **FAIL**\\n2. Critical: missing null check"}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10}}))
""",
        )
        rc, out = _run_delegate(self.repo, "checker", env_extra={"CODEX_BIN": str(fake_fail_verdict)})
        self.assertEqual(rc, 0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["checker_verdict"], "FAIL")

        fake_missing_verdict = _make_fake_runner(
            self.tmp,
            "fake_codex_no_verdict",
            """
import json, sys
_ = sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": "th-v2"}))
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Here is commentary on (PASS / FAIL) criteria without deciding."}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10}}))
""",
        )
        rc2, out2 = _run_delegate(self.repo, "checker", env_extra={"CODEX_BIN": str(fake_missing_verdict)})
        self.assertNotEqual(rc2, 0)
        self.assertFalse(out2["ok"])
        self.assertIsNone(out2["checker_verdict"])
        self.assertIn("missing explicit PASS/FAIL verdict", out2["error"])


class TestReadonlyAuditAndTimeoutEvidence(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_obj.name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _init_repo(self.repo)

    def tearDown(self) -> None:
        self.tmp_obj.cleanup()

    def test_readonly_catches_re_editing_already_dirty_file(self) -> None:
        (self.repo / "app.py").write_text("x = 2\n", encoding="utf-8")
        fake_mutator = _make_fake_runner(
            self.tmp,
            "fake_codex_mutate",
            """
import json, pathlib, sys
_ = sys.stdin.read()
pathlib.Path("app.py").write_text("x = 999\\n", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "th-mut"}))
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Verdict: PASS"}}))
print(json.dumps({"type": "turn.completed"}))
""",
        )
        rc, out = _run_delegate(self.repo, "checker", env_extra={"CODEX_BIN": str(fake_mutator)})
        self.assertNotEqual(rc, 0)
        self.assertFalse(out["ok"])
        self.assertTrue(out["readonly_violation"])
        self.assertEqual(out["readonly_audit"], "violated")

    def test_readonly_catches_sneaky_commit_leaving_clean_tree(self) -> None:
        fake_committer = _make_fake_runner(
            self.tmp,
            "fake_codex_commit",
            """
import json, pathlib, subprocess, sys
_ = sys.stdin.read()
pathlib.Path("app.py").write_text("x = 42\\n", encoding="utf-8")
subprocess.run(["git", "add", "app.py"], check=True)
subprocess.run(["git", "commit", "-m", "sneaky"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(json.dumps({"type": "thread.started", "thread_id": "th-cmt"}))
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Verdict: PASS"}}))
print(json.dumps({"type": "turn.completed"}))
""",
        )
        rc, out = _run_delegate(self.repo, "checker", env_extra={"CODEX_BIN": str(fake_committer)})
        self.assertNotEqual(rc, 0)
        self.assertFalse(out["ok"])
        self.assertTrue(out["readonly_violation"])
        self.assertEqual(out["readonly_audit"], "violated")

    def test_readonly_does_not_false_positive_on_bridge_logs_even_if_unignored(self) -> None:
        (self.repo / ".gitignore").write_text("", encoding="utf-8")
        _git(self.repo, "add", ".gitignore")
        _git(self.repo, "commit", "-m", "unignore agent")

        fake_clean = _make_fake_runner(
            self.tmp,
            "fake_codex_clean",
            """
import json, sys
_ = sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": "th-ok"}))
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Verdict: PASS"}}))
print(json.dumps({"type": "turn.completed"}))
""",
        )
        rc, out = _run_delegate(self.repo, "checker", env_extra={"CODEX_BIN": str(fake_clean)})
        self.assertEqual(rc, 0, msg=json.dumps(out, ensure_ascii=False))
        self.assertTrue(out["ok"])
        self.assertFalse(out["readonly_violation"])
        self.assertEqual(out["readonly_audit"], "clean")

    def test_readonly_reports_unverified_outside_git_repo(self) -> None:
        non_git = self.tmp / "plain_dir"
        non_git.mkdir()
        fake_clean = _make_fake_runner(
            self.tmp,
            "fake_codex_nongit",
            """
import json, sys
_ = sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": "th-ng"}))
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Verdict: PASS"}}))
print(json.dumps({"type": "turn.completed"}))
""",
        )
        rc, out = _run_delegate(non_git, "checker", env_extra={"CODEX_BIN": str(fake_clean)})
        self.assertEqual(rc, 0)
        self.assertEqual(out["readonly_audit"], "unverified")

    def test_timeout_preserves_partial_log_session_id_and_unique_run_ids(self) -> None:
        fake_hang = _make_fake_runner(
            self.tmp,
            "fake_codex_hang",
            """
import json, sys, time
_ = sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": "th-partial-99"}), flush=True)
time.sleep(10)
""",
        )
        rc, out = _run_delegate(
            self.repo,
            "checker",
            env_extra={"CODEX_BIN": str(fake_hang)},
            extra_args=["--timeout", "1"],
        )
        self.assertEqual(rc, 124)
        self.assertFalse(out["ok"])
        self.assertTrue(out["infra_failure"])
        self.assertEqual(out["session_id"], "th-partial-99")
        self.assertTrue(Path(out["raw_log"]).exists())
        self.assertIn("th-partial-99", Path(out["raw_log"]).read_text(encoding="utf-8"))

        rc2, out2 = _run_delegate(
            self.repo,
            "checker",
            env_extra={"CODEX_BIN": str(fake_hang)},
            extra_args=["--timeout", "1"],
        )
        self.assertEqual(rc2, 124)
        self.assertNotEqual(out["run_id"], out2["run_id"])
        self.assertNotEqual(out["raw_log"], out2["raw_log"])

    def test_builder_reports_pre_existing_dirty_files(self) -> None:
        (self.repo / "user_wip.txt").write_text("do not delete me\n", encoding="utf-8")
        fake_dsh = _make_fake_runner(
            self.tmp,
            "fake_dsh_ok",
            """
import json, sys
_ = sys.stdin.read()
print(json.dumps({"type": "final", "sessionId": "dsh-1", "text": "STATUS: DONE"}))
""",
        )
        rc, out = _run_delegate(self.repo, "builder", env_extra={"DSH_BIN": str(fake_dsh)})
        self.assertEqual(rc, 0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["pre_existing_dirty"], ["user_wip.txt"])

    def test_host_runner_role_returns_clear_guidance(self) -> None:
        rc, out = _run_delegate(self.repo, "design-advisor")
        self.assertNotEqual(rc, 0)
        self.assertFalse(out["ok"])
        self.assertIn("runner='host'", out["error"])


class TestPackDiff(unittest.TestCase):
    def test_pack_diff_on_real_temp_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            env_git = ["git", "-C", str(repo)]
            subprocess.run([*env_git, "init", "-b", "main"], check=True, capture_output=True)
            subprocess.run([*env_git, "config", "user.name", "Test"], check=True, capture_output=True)
            subprocess.run([*env_git, "config", "user.email", "test@example.com"], check=True, capture_output=True)

            target = repo / "app.txt"
            target.write_text("line1\n", encoding="utf-8")
            subprocess.run([*env_git, "add", "."], check=True, capture_output=True)
            subprocess.run([*env_git, "commit", "-m", "init"], check=True, capture_output=True)
            base_sha = subprocess.run([*env_git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

            target.write_text("line1\nline2\n", encoding="utf-8")
            subprocess.run([*env_git, "add", "."], check=True, capture_output=True)
            subprocess.run([*env_git, "commit", "-m", "add line2"], check=True, capture_output=True)
            head_sha = subprocess.run([*env_git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

            out_file = repo / ".agent" / "tasks" / "task-1-review.diff"
            proc = subprocess.run(
                [sys.executable, str(PACK_DIFF_PY), "--cwd", str(repo), "--base", base_sha, "--out", str(out_file)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue(out_file.exists())
            content = out_file.read_text(encoding="utf-8")
            self.assertIn(f"# Review Package ({base_sha}..{head_sha})", content)
            self.assertNotIn("..HEAD)", content)
            self.assertIn("add line2", content)
            self.assertIn("+line2", content)

    def test_pack_diff_refuses_empty_and_dirty_and_binds_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            base_sha = _init_repo(repo)
            out_file = repo / ".agent" / "tasks" / "task-1-review.diff"

            # Empty diff refused
            empty_res = subprocess.run(
                [sys.executable, str(PACK_DIFF_PY), "--cwd", str(repo), "--base", base_sha, "--out", str(out_file)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(empty_res.returncode, 0)
            self.assertIn("Empty diff", empty_res.stderr)

            # Commit then dirty working tree refused
            (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
            _git(repo, "add", "app.py")
            _git(repo, "commit", "-m", "slice commit")
            head_sha = _git(repo, "rev-parse", "HEAD")

            (repo / "app.py").write_text("x = 3\n", encoding="utf-8")
            dirty_res = subprocess.run(
                [sys.executable, str(PACK_DIFF_PY), "--cwd", str(repo), "--base", base_sha, "--out", str(out_file)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(dirty_res.returncode, 0)
            self.assertIn("uncommitted changes", dirty_res.stderr)

            # Clean tree succeeds with bound metadata
            (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
            ok_res = subprocess.run(
                [
                    sys.executable,
                    str(PACK_DIFF_PY),
                    "--cwd",
                    str(repo),
                    "--base",
                    base_sha,
                    "--head",
                    "HEAD",
                    "--out",
                    str(out_file),
                    "--verify-cmd",
                    "pytest -q",
                    "--verify-exit-code",
                    "0",
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ok_res.returncode, 0, msg=ok_res.stderr)
            meta = json.loads(ok_res.stdout)
            self.assertEqual(meta["base_sha"], base_sha)
            self.assertEqual(meta["head_sha"], head_sha)
            self.assertEqual(meta["files_changed"], ["app.py"])
            pkg = out_file.read_text(encoding="utf-8")
            self.assertIn("Verify Command: `pytest -q`", pkg)
            self.assertIn("Working Tree: CLEAN", pkg)

    def test_pack_diff_whole_branch_inventory_and_single_commit_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            branch_base = _init_repo(repo)
            (repo / "src").mkdir()
            (repo / "src" / "a.py").write_text("a = 1\n", encoding="utf-8")
            _git(repo, "add", "src/a.py")
            _git(repo, "commit", "-m", "slice 1")
            slice1_sha = _git(repo, "rev-parse", "HEAD")

            (repo / "src" / "b.py").write_text("b = 2\n", encoding="utf-8")
            _git(repo, "add", "src/b.py")
            _git(repo, "commit", "-m", "slice 2")
            head_sha = _git(repo, "rev-parse", "HEAD")

            out_full = repo / ".agent" / "tasks" / "final-branch-review.md"
            res = subprocess.run(
                [
                    sys.executable,
                    str(PACK_DIFF_PY),
                    "--whole-branch",
                    "--no-diff",
                    "--cwd",
                    str(repo),
                    "--base",
                    branch_base,
                    "--head",
                    "HEAD",
                    "--dataflow",
                    "input -> transform -> export",
                    "--out",
                    str(out_full),
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, msg=res.stderr)
            meta = json.loads(res.stdout)
            self.assertTrue(meta["whole_branch"])
            self.assertEqual(meta["commit_count"], 2)
            self.assertEqual(meta["base_sha"], branch_base)
            self.assertEqual(meta["head_sha"], head_sha)
            self.assertNotIn("single_commit_warning", meta)
            body = out_full.read_text(encoding="utf-8")
            self.assertIn("# Whole-Branch Final Review Package", body)
            self.assertIn("input -> transform -> export", body)
            self.assertIn("Coverage Scope", body)
            self.assertIn("src/a.py", body)
            self.assertIn("src/b.py", body)

            # Misusing last-slice base triggers single_commit_warning
            out_warn = repo / ".agent" / "tasks" / "warn-review.md"
            res_warn = subprocess.run(
                [
                    sys.executable,
                    str(PACK_DIFF_PY),
                    "--whole-branch",
                    "--no-diff",
                    "--cwd",
                    str(repo),
                    "--base",
                    slice1_sha,
                    "--head",
                    "HEAD",
                    "--out",
                    str(out_warn),
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res_warn.returncode, 0, msg=res_warn.stderr)
            meta_warn = json.loads(res_warn.stdout)
            self.assertIn("single_commit_warning", meta_warn)
            self.assertIn("SCOPE WARNING", out_warn.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
