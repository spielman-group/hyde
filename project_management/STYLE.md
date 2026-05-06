# Hyde Style Guide

## Imports
- Do not alias Hyde internal modules.
- Use normal scientific aliases like `np`, `plt`, and `pd`.
- Route Qt imports through `qtutils`, not raw Qt bindings.

## UI Boundary
- If non-UI callbacks touch Qt widgets, route them onto the main thread.
- GUI code may hold only transient state needed to generate commands or render UI.

## Public API
- Anything exported from `hyde/__init__.py` is public and must have proper docstrings.

## Default Bias
- Prefer the smallest clear change.
- Avoid extra abstractions, compatibility shims, and speculative infrastructure unless explicitly required.
