"""Centralized path definitions for the Hyde package."""

import os
import tempfile

HYDE_DIR = os.path.dirname(os.path.abspath(__file__))
HYDE_PKG_DIR = HYDE_DIR
APPLICATION_NAME = "hyde"

CONNECTION_FILE = os.path.join(
    tempfile.mkdtemp(prefix="hyde-session-"),
    "kernel-hyde.json",
)

# Path to the splash SVG
SPLASH_SVG = os.path.join(HYDE_DIR, "hyde.svg")

# Path to the Kernel Launcher script
KERNEL_LAUNCHER = os.path.join(
    HYDE_DIR, "execution", "kernel_launcher.py"
)

# --- Project Management Paths ---

# Default parent directory used when prompting for new/open project paths.
DEFAULT_PROJECTS_DIR = os.path.join(os.path.expanduser("~"), "HydeProjects")

# Repo-stored default project template copied when creating a new project.
PROJECT_TEMPLATES_DIR = os.path.join(HYDE_DIR, "project_templates")
DEFAULT_PROJECT_TEMPLATE = os.path.join(PROJECT_TEMPLATES_DIR, "default.hy")


def get_project_paths(project_dir):
    """Return the standard paths inside a Hyde ``.hy`` project package."""
    project_dir = os.path.abspath(project_dir)
    procedures_dir = os.path.join(project_dir, "procedures")
    procedures_init = os.path.join(procedures_dir, "__init__.py")
    return project_dir, procedures_dir, procedures_init
