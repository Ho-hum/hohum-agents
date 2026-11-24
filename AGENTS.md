# hohum-agents Repository Guidelines

## Purpose
This repository provides a model-agnostic multi-agent development specification (`docs/`), a portable scheduling skill (`skills/hohum-agents/`), hardened CLI delegation scripts (`scripts/`), and role profile templates (`templates/`).

## Verification Command
Run the unit test suite before committing any script changes:
```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Non-Negotiable Rules
- **Zero hardcoded personal paths or credentials**: Keep `docs/` strictly model-agnostic; keep machine-specific paths and model overrides in `*.local.json` (git-ignored) or environment variables (`DSH_BIN`, `CODEX_BIN`).
- **Standard library only**: Scripts under `skills/hohum-agents/scripts/` must run on Python 3.10+ with zero third-party pip dependencies.
- **Read-only safety**: Read-only roles must enforce both runner sandbox flags and pre/post `git status` verification.
