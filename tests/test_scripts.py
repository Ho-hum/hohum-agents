from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "skills" / "hohum-agents" / "scripts"


def load_module(name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(name, str(file_path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


delegate = load_module("delegate", SCRIPTS_DIR / "delegate.py")


class TestDelegateParsersAndConfig(unittest.TestCase):
    def test_load_example_roles(self) -> None:
        roles = delegate.load_roles(SCRIPTS_DIR / "roles.example.json")
        for expected in ("scout", "builder", "builder-mech", "checker", "tech-advisor", "builder-escalation"):
            self.assertIn(expected, roles)
        self.assertTrue(roles["scout"]["readonly"])
        self.assertTrue(roles["checker"]["readonly"])
        self.assertFalse(roles["builder"]["readonly"])

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

            out_file = repo / ".agent" / "tasks" / "task-1-review.diff"
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "pack_diff.py"), "--cwd", str(repo), "--base", base_sha, "--out", str(out_file)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue(out_file.exists())
            content = out_file.read_text(encoding="utf-8")
            self.assertIn("add line2", content)
            self.assertIn("+line2", content)


if __name__ == "__main__":
    unittest.main()
