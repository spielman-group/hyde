# Hyde

Hyde is a standalone labscript-suite analysis application: an MDI desktop shell with an
authoritative Python kernel behind it.

## Product Goal
Provide an integrated environment for tables, figures, procedures, and a Python
terminal while keeping the GUI separate from scientific state.

## Version 1 Goals
- one MDI application for figures, tables, browsers, and terminal
- kernel-authoritative execution through IPython
- reproducible GUI actions
- live-reactive tables and first-class figure windows
- portable `.hy` project packages
- compatibility with existing lyse-style messaging

## Non-Goals
- instrument control
- replacing `runmanager` or `blacs`
- arbitrary third-party plugin loading
- built-in code editing
