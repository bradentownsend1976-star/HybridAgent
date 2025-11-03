import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from hybrid_agent import loop


class StripDiffTests(unittest.TestCase):
    def test_strip_code_fences_handles_diff_language(self) -> None:
        original = """```diff
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-old
+new
```
"""
        stripped = loop._strip_code_fences(original)
        self.assertEqual(
            stripped, "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new"
        )

    def test_looks_like_unified_diff_accepts_context_style(self) -> None:
        context_diff = textwrap.dedent(
            """\
*** 1,3 ***
--- a/file.txt
+++ b/file.txt
*** 1 ****
-old line
--- 1 ----
+new line
"""
        )
        self.assertTrue(loop._looks_like_unified_diff(context_diff))

    def test_coerce_unified_rewrites_single_line(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "hello.py"
            target.write_text("print('old')\n", encoding="utf-8")
            coerced = loop._coerce_unified(
                "+print('new')",
                target_basename="hello.py",
                target_file=target,
            )
        self.assertIsNotNone(coerced)
        self.assertTrue(loop._looks_like_unified_diff(coerced or ""))


class SolveRequestTests(unittest.TestCase):
    def test_fallback_to_codex_and_logs(self) -> None:
        diff_response = """```diff
--- a/sample.py
+++ b/sample.py
@@ -0,0 +1 @@
+print('ok')
```"""
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "ws"
            log_path = Path(td) / "run.jsonl"
            with (
                mock.patch(
                    "hybrid_agent.loop.ollama_generate_diff",
                    return_value=(False, "", "ollama down"),
                ) as ollama_mock,
                mock.patch(
                    "hybrid_agent.loop.codex_generate_diff",
                    return_value=(True, diff_response, "codex ok"),
                ) as codex_mock,
            ):
                result = loop.solve_request(
                    prompt="Change sample",
                    files=[],
                    max_ollama_attempts=1,
                    ollama_model="phi3",
                    codex_models="codex",
                    workspace_dir=str(workspace),
                    log_file=str(log_path),
                )

                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.source, "codex")
                expected_diff = (
                    "--- a/sample.py\n+++ b/sample.py\n@@ -0,0 +1 @@\n+print('ok')"
                )
                self.assertEqual(result.diff_text.strip(), expected_diff)
                self.assertTrue((workspace / "last.diff").exists())
                archive_dir = workspace / "diffs"
                archived = list(archive_dir.glob("*.diff"))
                self.assertEqual(len(archived), 1)
                self.assertIn(expected_diff, archived[0].read_text(encoding="utf-8"))
                self.assertTrue(ollama_mock.called)
                self.assertTrue(codex_mock.called)
                log_entries = log_path.read_text(encoding="utf-8").strip().splitlines()
                self.assertEqual(len(log_entries), 1)
                entry = json.loads(log_entries[0])
                self.assertEqual(entry["source"], "codex")
                self.assertEqual(entry["attempts"][0]["backend"], "ollama")
                self.assertEqual(entry["attempts"][-1]["backend"], "codex-cli")

    def test_validator_rejects_diff(self) -> None:
        diff_response = """--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-print('hi')
+print('bye')"""
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "ws"
            root_dir = Path(td)
            config_dir = root_dir / "config"
            config_dir.mkdir(parents=True)
            validator = config_dir / "validate_diff.py"
            validator.write_text(
                textwrap.dedent(
                    """\
import sys
print("Diff rejected", file=sys.stderr)
sys.exit(1)
"""
                ),
                encoding="utf-8",
            )
            with (
                mock.patch(
                    "hybrid_agent.loop.ollama_generate_diff",
                    return_value=(False, "", "ollama down"),
                ),
                mock.patch(
                    "hybrid_agent.loop.codex_generate_diff",
                    return_value=(True, diff_response, "codex ok"),
                ),
            ):
                result = loop.solve_request(
                    prompt="Change app",
                    files=[],
                    max_ollama_attempts=0,
                    ollama_model="phi3",
                    codex_models="codex",
                    workspace_dir=str(workspace),
                    root_dir=str(root_dir),
                )
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.source, "validator")
        self.assertIn("Diff rejected", result.message)

    def test_validator_rewrites_diff(self) -> None:
        original_diff = """--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-print('hi')
+print('bye')"""
        rewritten_diff = """--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-print('hi')
+print('HELLO')"""
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "ws"
            root_dir = Path(td)
            (root_dir / "config").mkdir(parents=True)
            (root_dir / "config" / "validate_diff.py").write_text(
                textwrap.dedent(
                    f"""\
import sys
sys.stdout.write({rewritten_diff!r})
"""
                ),
                encoding="utf-8",
            )
            with (
                mock.patch(
                    "hybrid_agent.loop.ollama_generate_diff",
                    return_value=(False, "", "ollama down"),
                ),
                mock.patch(
                    "hybrid_agent.loop.codex_generate_diff",
                    return_value=(True, original_diff, "codex ok"),
                ),
            ):
                result = loop.solve_request(
                    prompt="Change app",
                    files=[],
                    max_ollama_attempts=0,
                    ollama_model="phi3",
                    codex_models="codex",
                    workspace_dir=str(workspace),
                    root_dir=str(root_dir),
                )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.diff_text.strip(), rewritten_diff.strip())
        self.assertIn("HELLO", result.diff_text)

    def test_plan_only_returns_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "ws"
            result = loop.solve_request(
                prompt="Update docs",
                files=[],
                max_ollama_attempts=0,
                ollama_model="phi3",
                codex_models="codex",
                workspace_dir=str(workspace),
                plan_only=True,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.source, "plan")
        self.assertIn("Prompt ready", result.message)
        self.assertTrue(result.diff_text.startswith("You are"))

    def test_response_cache_reused(self) -> None:
        diff_response = """--- a/data.txt
+++ b/data.txt
@@ -1 +1 @@
-old
+new"""
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "ws"
            cache_dir = Path(td) / "cache"
            cache_key = "cachekey123"
            cache_metadata = {"note": "unit-test"}
            with (
                mock.patch(
                    "hybrid_agent.loop.ollama_generate_diff",
                    return_value=(False, "", "ollama down"),
                ),
                mock.patch(
                    "hybrid_agent.loop.codex_generate_diff",
                    return_value=(True, diff_response, "codex ok"),
                ),
            ):
                first = loop.solve_request(
                    prompt="Change data",
                    files=[],
                    max_ollama_attempts=1,
                    ollama_model="phi3",
                    codex_models="codex",
                    workspace_dir=str(workspace),
                    cache_dir=str(cache_dir),
                    cache_key=cache_key,
                    cache_metadata=cache_metadata,
                )
            self.assertEqual(first.returncode, 0)
            self.assertTrue((cache_dir / f"{cache_key}.diff").exists())

            def fail(*_args, **_kwargs):
                raise AssertionError(
                    "Backend should not have been invoked when cache is warm."
                )

            with (
                mock.patch("hybrid_agent.loop.ollama_generate_diff", side_effect=fail),
                mock.patch("hybrid_agent.loop.codex_generate_diff", side_effect=fail),
            ):
                cached = loop.solve_request(
                    prompt="Change data",
                    files=[],
                    max_ollama_attempts=1,
                    ollama_model="phi3",
                    codex_models="codex",
                    workspace_dir=str(workspace),
                    cache_dir=str(cache_dir),
                    cache_key=cache_key,
                )
        self.assertEqual(cached.returncode, 0)
        self.assertEqual(cached.source, "cache")
        self.assertIn("[cached]", cached.message)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
