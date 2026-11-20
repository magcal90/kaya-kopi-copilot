"""Regression test for launching the Streamlit entry point from the app directory."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class StreamlitEntrypointTest(unittest.TestCase):
    def test_entrypoint_imports_app_package_from_app_directory(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["OPENAI_API_KEY"] = "test-placeholder"
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment["KAYA_CHAT_DB"] = str(
                Path(temporary_directory) / "chat-checkpoints.sqlite3"
            )
            result = subprocess.run(
                [sys.executable, "streamlit_app.py"],
                cwd=repository_root / "app",
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        combined_output = result.stdout + result.stderr
        self.assertNotIn("No module named 'app'", combined_output)
        self.assertEqual(result.returncode, 0, combined_output)


if __name__ == "__main__":
    unittest.main()
