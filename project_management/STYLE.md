# Hyde Style Guide

This document defines the coding standards and best practices for the Hyde project.

## 1. Import Conventions

### 1.1 No Internal Aliasing
Avoiding the use of `import module as alias` is heavily discouraged in this codebase for internal packages to ensure explicit namespace tracing. Always use fully-qualified references.
- **Incorrect:** `import hyde.recreation_registry as registry`
- **Correct:** `import hyde.recreation_registry`

### 1.2 Standard Library Exceptions
Explicit renames for common standard library modules are generally avoided unless there is a strong reason (e.g., namespace collision). `import datetime` is preferred over `import datetime as dt`.

### 1.3 Scientific Python Exceptions
Standard industry-recognized aliases for the scientific Python stack are permitted and encouraged:
- `import numpy as np`
- `import matplotlib.pyplot as plt`
- `import pandas as pd`

## 2. UI Framework Boundary
Do not ever import `PyQt5`, `PyQt6`, `PySide2`, or `PySide6` natively. You must route all imports through the labscript-suite's `qtutils` compatibility layer.
- **Example:** `from qtutils.qt.QtWidgets import QMainWindow`

## 3. Threading and UI Interaction
If an IPython response or a zero-MQ callback touches the UI, you MUST route it to the main GUI thread using `qtutils.inmain_decorator` or similar helpers.

## 4. Documentation
### 4.1 Public API Documentation
Anything exposed from `hyde/__init__.py` is part of Hyde's public API and must be documented with docstrings and parameter/behavior descriptions suitable for generated API documentation.
