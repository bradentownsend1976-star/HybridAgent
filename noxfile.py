"""Nox automation for HybridAgent."""

from __future__ import annotations

import pathlib

import nox

REPO_ROOT = pathlib.Path(__file__).parent

nox.options.sessions = (
    "lint",
    "typecheck",
    "tests",
    "security",
    "audit",
)
nox.options.reuse_existing_virtualenvs = True
nox.options.error_on_external_run = False


def install_package(session: nox.Session, *packages: str) -> None:
    if packages:
        session.install(*packages)


@nox.session
def lint(session: nox.Session) -> None:
    """Run style and import checks."""
    install_package(session, "ruff", "black", "isort")
    session.run("ruff", "check", ".")
    session.run("black", "--check", ".")
    session.run("isort", "--check-only", ".")


@nox.session
def typecheck(session: nox.Session) -> None:
    """Run static type checkers."""
    install_package(session, "mypy", "pyright")
    session.run("pyright")
    session.run("mypy", "src")


@nox.session
def tests(session: nox.Session) -> None:
    """Run test suite with coverage."""
    install_package(session, "pytest", "pytest-cov", "hypothesis", "coverage[toml]")
    session.env["PYTHONPATH"] = "src"
    session.run("pytest", "--cov=src", "--cov-report=term-missing")


@nox.session
def security(session: nox.Session) -> None:
    """Run static security scanners."""
    install_package(session, "bandit", "semgrep")
    session.run("bandit", "-r", "src")
    try:
        session.run("semgrep", "scan", "--config", "p/ci", "--error")
    except nox.command.CommandFailed:
        session.log("semgrep p/ci rules failed; retrying with --config auto")
        session.run("semgrep", "scan", "--config", "auto", "--error")


@nox.session
def audit(session: nox.Session) -> None:
    """Run dependency vulnerability scanning."""
    install_package(session, "pip-audit", "safety")
    session.run("pip-audit")
    session.run("safety", "check")
