import os
import signal
import subprocess
import sys
import textwrap
import unittest


class TestKernelLauncher(unittest.TestCase):
    def test_hyde_signal_marker_survives_real_zprocess_killlock_wrapping(self):
        code = textwrap.dedent(
            """
            import os
            import signal

            import hyde

            hyde.gui_mode(True)
            import labscript_utils.ls_zprocess
            hyde.gui_mode(True)
            hyde.gui_mode(False)
            hyde.gui_mode(True)

            os.kill(os.getpid(), signal.SIGTERM)
            """
        )
        env = dict(os.environ)
        repo_root = os.path.dirname(os.path.dirname(__file__))
        env["PYTHONPATH"] = os.pathsep.join(
            path
            for path in (repo_root, env.get("PYTHONPATH", ""))
            if path
        )

        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=repo_root,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )

        self.assertEqual(
            result.returncode,
            -signal.SIGTERM,
            result.stderr,
        )
        self.assertIn("Received SIGTERM", result.stderr)
        self.assertNotIn("Another SIGTERM handler has been installed", result.stderr)


if __name__ == "__main__":
    unittest.main()
