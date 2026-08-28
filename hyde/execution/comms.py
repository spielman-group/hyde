"""Lane 2 Jupyter ``comm`` target names shared by the kernel and the GUI.

These names are the wire contract between kernel-side Hyde code and the GUI
plugins that consume it. They live outside ``hyde.user_interface`` so the
kernel process never imports GUI or Qt modules to learn a target name.
"""

FIGURE_COMM_TARGET = "hyde_figure"
