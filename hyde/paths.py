"""Centralized path definitions for the Hyde package.

All path derivation should go through this module rather than
computing paths ad-hoc with multi-level os.path.dirname chains.
"""

import os
import tempfile

# The root directory of the installed hyde package
HYDE_PKG_DIR = os.path.dirname(os.path.abspath(__file__))

# Per-session runtime directory (unique per process, avoids collisions
# between concurrent Hyde instances and avoids writing into the package tree)
_SESSION_DIR = tempfile.mkdtemp(prefix="hyde-session-")

# Kernel connection file: unique per session, living in a temp directory
CONNECTION_FILE = os.path.join(_SESSION_DIR, "kernel-hyde.json")

# Path to the splash SVG
SPLASH_SVG = os.path.join(HYDE_PKG_DIR, "hyde.svg")

# Path to the Execution Controller script
EXECUTION_CONTROLLER = os.path.join(
    HYDE_PKG_DIR, "execution", "execution_controller.py"
)

# Path to the Kernel Launcher script
KERNEL_LAUNCHER = os.path.join(
    HYDE_PKG_DIR, "execution", "kernel_launcher.py"
)
