import typer
from rich.console import Console

from .plugins import discover as discover_plugins

app = typer.Typer(
    add_completion=False,
    help="Friendly interface for HybridAgent's diff-generation tools.",
)


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", help="Show HybridAgent version and exit."
    )
):
    if version:
        try:
            import importlib.metadata as im

            ver = im.version("hybridagent")
        except Exception:
            ver = "0.0.0"
        print(ver)
        raise typer.Exit(0)


# Legacy bridges (doctor/plan/solve) — call into argparse CLI when available
@app.command("doctor")
def cmd_doctor():
    try:
        from .cli import main as legacy_main  # type: ignore

        raise SystemExit(legacy_main())
    except Exception:
        Console().print("[bold red]Doctor not available in legacy CLI.[/]")
        raise typer.Exit(1)


@app.command("plan")
def cmd_plan(
    prompt: str = typer.Option(..., "--prompt"), file: str = typer.Option(..., "--file")
):
    try:
        import sys

        from .cli import main as legacy_main  # type: ignore

        sys.argv = ["hybrid", "plan", "--prompt", prompt, "--file", file]
        raise SystemExit(legacy_main())
    except Exception:
        Console().print("[bold red]Plan not available in legacy CLI.[/]")
        raise typer.Exit(1)


@app.command("solve")
def cmd_solve(
    prompt: str = typer.Option(..., "--prompt"),
    file: str = typer.Option(..., "--file"),
    max_ollama_attempts: int = typer.Option(None, "--max-ollama-attempts"),
):
    try:
        import sys

        from .cli import main as legacy_main  # type: ignore

        argv = ["hybrid", "solve", "--prompt", prompt, "--file", file]
        if max_ollama_attempts is not None:
            argv += ["--max-ollama-attempts", str(max_ollama_attempts)]
        sys.argv = argv
        raise SystemExit(legacy_main())
    except Exception:
        Console().print("[bold red]Solve not available in legacy CLI.[/]")
        raise typer.Exit(1)


# self-repair wired in below (import added later in this script)


@app.command("self-repair")
def self_repair(
    scope: str = "src/",
    tests: str = "pytest -q",
    max_iters: int = 5,
    timeout_sec: float = 900.0,
    stall_limit: int = 2,
    dry_run: bool = False,
) -> int:
    """Run tests; if failing, attempt automated repair (Phase 6)."""


def main() -> None:  # console_scripts entrypoint expects this
    # Typer apps are callable; this invokes the CLI.
    # Returning None is fine; console script wraps SystemExit.
    app()


exec_app = typer.Typer(help="Run executor plugins")
app.add_typer(exec_app, name="exec")


@exec_app.command("mouth-sync")
def exec_mouth_sync(
    audio: str = typer.Option(..., "--audio", help="Path to audio file (wav/mp3)"),
    fps: int = typer.Option(30, "--fps", help="Output FPS for timeline"),
    out: str = typer.Option("visemes.json", "--out", help="Output JSON file"),
) -> None:
    """
    Run the mouth-sync executor (stub) and emit viseme JSON.
    """
    console = Console()
    plugins = discover_plugins()
    execs = plugins.get("executors", [])
    cls = next((e for e in execs if getattr(e, "name", "") == "mouth-sync"), None)
    if cls is None:
        console.print(
            "[red][ERR][/red] mouth-sync executor not found via plugin discovery."
        )
        raise SystemExit(2)
    inst = cls()  # type: ignore[call-arg]
    result = inst.run(audio=audio, fps=fps, out=out)
    console.print(
        f"[green][OK][/green] wrote {out} ({len(result.get('frames', []))} frames)"
    )
