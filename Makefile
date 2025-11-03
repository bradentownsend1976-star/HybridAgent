.PHONY: run solve test lint format typecheck security audit coverage hooks fuzz ci

run:
	@PYTHONPATH=src python3 -m hybrid_agent.cli --version

solve:
	@PYTHONPATH=src python3 -m hybrid_agent.cli solve --prompt "$(P)" $(F)

test:
	@PYTHONPATH=src python3 -m pytest -q

lint:
	@ruff check .
	@black --check .
	@isort --check-only .

format:
	@ruff check . --fix
	@black .
	@isort .

typecheck:
	@pyright
	@mypy src

security:
	@bandit -c bandit.yaml -r src
	@semgrep scan --config p/ci --error || semgrep scan --config auto

audit:
	@pip-audit
	@safety check || true

coverage:
	@PYTHONPATH=src python3 -m pytest --cov=src --cov-report=term-missing

hooks:
	@bash tools/post_hooks.sh run

fuzz:
	@PYTHONPATH=src python3 tests/fuzz_diff_apply.py

ci: lint typecheck security audit test
