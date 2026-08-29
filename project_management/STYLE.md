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
- For package-owned IR families, the IR module lives beside the lowerer as
  `hyde/features/<package>_ir.py`, paired with
  `hyde/features/<package>_features.py`.
- For widget-local workflow IR families that compose multiple packages, the
  plugin-local IR module name is `<widget>_IR.py`.
- Non-neutral supporting material for an IR family should live in another
  plugin-local module, not under `hyde.user_interface.shared`.

## UI Boundary
- If non-UI callbacks touch Qt widgets, route them onto the main thread.
- Connect Qt signals to bound methods, not to `functools.partial` or closures that
  capture the receiver. PyQt tracks a bound-method receiver weakly and disconnects
  when its owner disappears; a partial or closure is an ordinary Python object that
  Qt keeps and calls regardless. If cyclic GC clears that callable while Qt still
  holds a pending emission - `destroyed`, `deleteLater`, anything queued - the next
  event drain invokes a cleared callable and segfaults the interpreter rather than
  raising. Pass per-connection data through a Qt property on the sender and read it
  back in the slot.
- Beware that such a crash surfaces far from its cause. It is GC-threshold sensitive,
  so it presents as an intermittent segfault in whichever unrelated code next pumps
  the event loop, and unrelated edits appear to cause or cure it by shifting
  allocation. Suspect object lifetimes and signal receivers before suspecting the
  code the traceback points at.
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
            ├── HydeFileDialog
            │   ├── project target dialogs
            │   ├── import/export target dialogs
            │   └── ...
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
  plugin-local `HydeFigureDialogWidget`, with concrete dialogs inheriting from
  that class.
- Target-selecting project and file dialogs should follow the same pattern through
  shared `HydeFileDialog` / `HydeFileWidget` infrastructure in
  `hyde.user_interface.base_hyde_widgets`. Keep generic chooser policy and optional
  overwrite confirmation there, and keep operation-specific exceptions in the
  concrete dialog. `File -> Save` remains a direct hidden dispatch rather than a
  chooser dialog.
- When multiple figure-facing surfaces need one canonical user-facing name for traces
  or analogous figure elements, use the feature-side matplotlib trace-record
  contract directly or through plugin-local helper tooling that delegates to it.
  Do not duplicate widget-local string formatting.
- Canonical trace display names follow this contract:
  - `{label}: {y} vs {x}` when `label` and `x` exist
  - `{label}: {y}` when `label` exists and `x` does not
  - `{y} vs {x}` when `label` does not exist and `x` exists
  - `{y}` when `y` exists and the earlier cases do not apply
  - `{label}` when `label` exists and no canonical `y` name exists
  - trace ID fallback only when neither `label` nor canonical source names exist
- Figure windows may use visible titles of the form
  `{Figure_name}: {trace display names}`. This affects visible chrome only. Stable
  subwindow identity and save/restore naming must remain unchanged. For the first
  pass, rely on the native title-bar truncation behavior rather than adding custom
  Hyde ellipsis logic.
- Treat code-built widget trees as exceptions that need a concrete reason, such as a
  third-party runtime widget or a layout that is materially impossible or misleading
  to express in Qt Designer.
- For color selection, prefer the plugin-local matplotlib-aware color picker in
  the figure dialog family rather than feature-local color widgets.
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
- Those `hyde/__init__.py` docstrings are the primary API documentation.
- Public functions exported from `hyde/__init__.py` must use NumPy docstring
  style: a summary line followed by standard sections such as `Parameters`,
  `Returns`, `Raises`, and `Notes` when those sections apply.

## Default Bias
- Prefer the smallest clear change.
- Avoid extra abstractions, compatibility shims, and speculative infrastructure unless explicitly required.
