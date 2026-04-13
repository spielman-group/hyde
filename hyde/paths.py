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

# --- Project Management Paths ---

# Default parent directory used when prompting for new/open project paths.
DEFAULT_PROJECTS_DIR = os.path.join(os.path.expanduser("~"), "HydeProjects")

# Repo-stored default project template copied when creating a new project.
PROJECT_TEMPLATES_DIR = os.path.join(HYDE_PKG_DIR, "project_templates")
DEFAULT_PROJECT_TEMPLATE = os.path.join(PROJECT_TEMPLATES_DIR, "default.hy")
DEFAULT_MASTER_TEMPLATE = os.path.join(
    DEFAULT_PROJECT_TEMPLATE, "procedures", "master.py"
)


def get_project_paths(project_dir):
    """Return the standard paths inside a Hyde ``.hy`` project package."""
    project_dir = os.path.abspath(project_dir)
    procedures_dir = os.path.join(project_dir, "procedures")
    master_script = os.path.join(procedures_dir, "master.py")
    return project_dir, procedures_dir, master_script
