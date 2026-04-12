# Hyde: Vision and Requirements

## The Product Vision
Hyde is a standalone labscript-suite application designed for Pythonic, Igor-Pro-like data analysis and plotting.

It provides scientists with a unified environment where figures, tables, a Python terminal, and related tools live inside a single Desktop application interface (MDI). However, unlike legacy tools, Hyde completely isolates the GUI logic from the execution logic, enforcing a clean boundary between "display" and "data state".

Hyde is intended to be an optional modern replacement for `lyse` while remaining fully compatible with the suite's messaging path used by `runmanager` and `blacs`.

## Core Goals (Version 1)
- **Unified Interface:** A single PyQt MDI application window housing all figures, tables, and the command pipeline.
- **Python-Native:** A built-in IPython terminal driving all actions.
- **GUI-Generated Replayability:** Every action in the GUI (e.g. editing a graph, fitting a curve) must generate raw Python code that is sent to the terminal. Users should be able to view and save the script that generated their UI state.
- **Session Persistence:** Application state, figures, table contents, and the terminal history must be saved as a portable `.hy` project directory package format.
- **Live Reactivity:** Figures and tables must live-refresh when the underlying data in the Python namespace changes.
- **Suite Compatibility:** Must accept incoming messages currently designed for `lyse`.

## Non-Goals (What Hyde is NOT)
- Hyde is **not** an experiment-control application.
- It does **not** perform instrument control.
- It does **not** replace `runmanager` or `blacs`.
- It does **not** feature a generic plugin architecture (just standard Python extensibility).
- It does **not** host a built-in code editor (it will launch the user's OS-default text editor for `.py` files).
