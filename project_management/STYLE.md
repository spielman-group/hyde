# Hyde Style Guide

## Imports
- Do not alias Hyde internal modules.
- Use normal scientific aliases like `np`, `plt`, and `pd`.
- Route Qt imports through `qtutils`, not raw Qt bindings.

## Naming
- In classes, leading `_name` members indicate private implementation details.
- At module scope, do not use leading `_` for private functions or private classes.
- At module scope, leading `_NAME` or `_name` is reserved for private module-global
  constants or variables.
- For first-class figure elements, `label` means the raw plotted label metadata from
  matplotlib, while `display_name` means Hyde's canonical synthesized user-facing
  identifier. Do not reuse `label` to mean the canonical display string.
- First-party plugin package names under `hyde.user_interface.plugins` should encode
  their primary widget family:
  - `*_tool` for `HydeToolWidget` plugins
  - `*_interactive` for `HydeInteractiveWidget` plugins
  - `*_dialog` for `HydeDialog` / `HydeDialogWidget` plugins
  - no suffix for infrastructure or non-widget plugins for now
- Branch naming follows the same split:
  - `plugins/<plugin_name>` for plugin-scoped work
  - `refactor` for cross-cutting refactors

## UI Boundary
- If non-UI callbacks touch Qt widgets, route them onto the main thread.
- GUI code may hold only transient state needed to generate commands or render UI.

## Widget Hierarchy

Use the widget base classes as the functionality path for plugins. Prefer inheriting
from the narrowest Hyde base that already carries the behavior you need rather than
rebuilding that behavior locally.

```text
QtWidgets
├── QWidget
│   └── HydeToolWidget
│       ├── ProcedureBrowser
│       ├── LoggingWindow
│       ├── PythonVariables
│       └── HydeInteractiveWidget
│           ├── TableWidget
│           └── FigureWindow
└── QDialog
    └── HydeDialog
        ├── SaveWindowDialog
        └── HydeDialogWidget
            ├── NewTableDialog
            ├── NewFigureDialog
            └── HydeFigureDialogWidget
                ├── TraceAppearanceDialog
                ├── AxisEditDialog
                ├── CurveFitDialog
                └── ...
```

## UI Conventions
- For Hyde-authored dialogs and tool-window bodies, prefer `.ui` files for static
  structure. Python should normally supply signal wiring, state synchronization,
  dynamic row/item creation, and runtime-only widgets rather than assembling large
  static layout trees in code.
- When multiple dialogs in one feature family share behavior, prefer a shared widget
  base class over free helper functions. For first-class figure dialogs, the default
  pattern is a `HydeDialogWidget` subclass dedicated to figure work, such as
  `HydeFigureDialogWidget`, with concrete dialogs inheriting from that class.
- When multiple figure-facing surfaces need one canonical user-facing name for traces
  or analogous figure elements, prefer shared figure helper tooling used through
  composition over duplicated widget-local string formatting.
- Canonical trace display names follow this contract:
  - `{label}: {y} vs {x}` when `label` and `x` exist
  - `{label}: {y}` when `label` exists and `x` does not
  - `{y} vs {x}` when `label` does not exist and `x` exists
  - `{y}` otherwise
- Figure windows may use visible titles of the form
  `{Figure_name}: {trace display names}`. This affects visible chrome only. Stable
  subwindow identity and save/restore naming must remain unchanged. For the first
  pass, rely on the native title-bar truncation behavior rather than adding custom
  Hyde ellipsis logic.
- Treat code-built widget trees as exceptions that need a concrete reason, such as a
  third-party runtime widget or a layout that is materially impossible or misleading
  to express in Qt Designer.
- For color selection, prefer the shared matplotlib-aware color picker in
  `hyde.user_interface.matplotlib_color_picker`.
- New Hyde color-entry surfaces should normally use `MatplotlibColorDialog` and/or
  `MatplotlibColorLineEdit` rather than raw `QColorDialog`, plain `QLineEdit`
  color fields, or feature-local color picker widgets.
- Treat this as the default Hyde color UI unless a surface has a specific product
  reason to require a different interaction model.
- The shared picker contract is:
  - the text field accepts matplotlib color names, RGB/RGBA tuple literals, and hex
    values
  - the dialog replaces stock custom colors with a named matplotlib color list
  - the named-color list should be ordered with common colors first, then the
    remaining named matplotlib colors
  - color-entry widgets should show a visible swatch and open the shared picker when
    the swatch is clicked
  - fields that allow matplotlib `"auto"` should preserve that value while showing a
    preview swatch for the effective resolved color when possible

## Public API
- Anything exported from `hyde/__init__.py` is public and must have proper docstrings.

## Default Bias
- Prefer the smallest clear change.
- Avoid extra abstractions, compatibility shims, and speculative infrastructure unless explicitly required.
