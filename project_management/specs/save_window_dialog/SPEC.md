# Save Window Dialog Specification

## Feature Checklist
- [x] Present a Hyde-native save-on-close dialog for saveable windows.
- [x] Allow the user to save a recreation macro, close without saving, or cancel the close.
- [x] Support overwrite confirmation when a chosen macro name already exists.
- [x] Support shift-click hide without prompting.
- [ ] Support figure, layout, and other non-table saveable windows.

## Purpose

The Save Window dialog is Hyde's generic close-time prompt for saveable MDI windows.
It asks whether the user wants to persist a recreation macro before the window closes.

The dialog does not own scientific state. It only collects the requested macro name and
drives the bounded project-file write that persists the window's recreation function.

## Initial Deployment Scope

The initial deployment activates this dialog only for table windows.

It includes:

- prompting when a table window is closed directly
- entering or editing the recreation macro name
- saving a parameterized recreation macro into `procedures/__init__.py`
- confirming overwrite before replacing an existing same-name function
- closing without saving
- canceling the close
- hiding the window immediately when the close button is shift-clicked

It does not include:

- application-wide save-all-on-quit flows
- figure, layout, or gizmo integration
- bulk macro management

## Window Layout

The dialog is a compact modal window containing:

- the prompt `Save window recreation macro as:`
- a single editable name field
- `Save`, `No Save`, `Help`, and `Cancel` buttons
- a tip about shift-click hide

## Visible Controls

- macro name field: `active`
- `Save`: `active`
- `No Save`: `active`
- `Help`: `active`
- `Cancel`: `active`
- shift-click hide tip: `active`

## Command Generation

The dialog does not execute scientific commands itself.
When the user chooses `Save`, it asks the active saveable window for its recreation
function source and writes that source into the project's bounded macro block inside
`procedures/__init__.py`. For tables, the saved macro takes parameters naming the live
kernel objects needed to reopen the table.

## Synchronization

Saving a macro must trigger the existing procedures reload path so the kernel rebuilds
its decorated macro registry and the GUI refreshes the relevant Windows submenu.

## Explicit Exclusions

- direct scientific execution from the dialog
- save-all-on-quit
- non-table saveable windows

## Future Work

- figure integration
- layout integration
- macro browser / rename / delete workflows
