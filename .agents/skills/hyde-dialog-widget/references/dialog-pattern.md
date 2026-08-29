# HydeDialogWidget Pattern

Default target shape for Hyde dialog plugins. Shared ownership, IR, and override
rules live in `.agents/protocols/hyde/widget-family.md`; this file is the
dialog-specific checklist.

## What The Base Owns

- footer button wiring
- backing preview string storage
- `OK` enablement from whether the backing string is non-empty
- default `OK` dispatch, `To IPython`, and `Copy`
- file-backed help through `help_filename`

The subclass owns loading the `.ui`, reading widget state, populating dynamic
rows, validation messages, cancel/revert behavior, and any `OK` policy that
wraps the shared dispatch path.

## Preview Contract

The backing string comes from the dialog's `widget_ir`:

```python
self.widget_ir = self.build_widget_ir(selection)
payload = "" if self.widget_ir is None else self.widget_ir.python_source(log=False)
self.set_preview_string(payload)
self.refresh_shell()
```

`HydeFileDialog.refresh_from_file_selection()` is the reference implementation:
subclasses supply `build_preview_state(...)` and inherit generation, validation,
and submission. Extend it through hook overrides and `super()`.

When displayed text must differ from the executable payload:

```python
self.set_preview_string(payload, display_text=display_preview)
```

Backing string is what executes and copies. Display text is an exception that the
spec must justify.

## Good Override Reasons

- `can_ok()` depends on local validation beyond payload presence
- `ok_dispatch_mode()` must be visible instead of hidden
- `handle_ok()` must validate, log, capture rollback, or do state bookkeeping
  around the shared dispatch
- `can_send_to_ipython()` intentionally disables visible emission in one mode

## Bad Override Reasons

- returning preview text the dialog already stores
- forwarding to base dispatch without extra policy
- restating base help behavior
- maintaining a second preview string mirroring the lower text widget
- assembling command Python instead of asking `widget_ir` for it

## New Plugin Checklist

- package name ends in `_dialog`
- static layout is in `.ui`
- the dialog subclasses `HydeDialogWidget`, or the family base where one exists
  (`HydeFileDialog` for target-selecting dialogs, `HydeFigureDialogWidget` for
  figure work)
- `widget_ir` is a real IR object, and the preview comes from its `python_source()`
- footer actions use the base class wherever possible
- the launcher passes `services=` and does not add a second dispatch path
- tests prove execute/copy/send behavior

## Normalization Checklist

- remove trivial payload getters; `preview_string()` is the backing contract
- remove trivial `To IPython` / `Copy` implementations
- collapse duplicate preview state onto the base backing string
- move locally assembled command text onto `widget_ir`
- move package-local string lowering into `hyde/features/<package>_features.py`,
  keeping validation and state normalization on the IR class
- verify `OK`, `To IPython`, and `Copy` share one backing string unless the
  spec says otherwise

## Feature-Specific Policy

Do not copy feature-specific dialog contracts into this reference. When a dialog
has feature-specific ownership, preview, identity, or dispatch rules, read the
active spec and the Hyde docs and apply this pattern around them.
