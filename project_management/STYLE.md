# Hyde Style Guide

## Imports
- Do not alias Hyde internal modules.
- Use normal scientific aliases like `np`, `plt`, and `pd`.
- Route Qt imports through `qtutils`, not raw Qt bindings.

## UI Boundary
- If non-UI callbacks touch Qt widgets, route them onto the main thread.
- GUI code may hold only transient state needed to generate commands or render UI.

## UI Conventions
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
