# Save Window Dialog Specification

## Feature Checklist
- [x] Present a Hyde-native save-on-close dialog for saveable windows.
- [x] Allow the user to save a recreation macro, close without saving, or cancel the close.
- [x] Support overwrite confirmation when a chosen macro name already exists.
- [x] Support shift-click hide without prompting.
- [ ] Activate the same generic save-window flow for first-class figure windows.
- [ ] Support figure, layout, and other non-table saveable windows.

## Purpose

The Save Window dialog is Hyde's generic close-time prompt for saveable MDI windows.
It asks whether the user wants to persist a recreation macro before the window closes.

The dialog does not own scientific state. It only collects the requested macro name and
drives the bounded project-file write that persists the window's recreation function.

## Generic Saveable-Window Contract

The dialog remains generic. A saveable window owns the feature-specific recreation data
and the lowering path that turns that data into bounded Python source for
`procedures/__init__.py`.

For tables, that recreation data is the table feature's internal state
(`TableState`), lowered through the table codec path.

For first-class figures, the analogous recreation data is the figure feature's IR
attached to the live matplotlib `Figure`. In Hyde, `IR` here means feature-specific
internal representation or internal state in the same sense as the existing
state-to-Python generation path used by `features/...` today. The figure PRD makes a
figure-specific choice that this IR lives in the kernel on the live figure. The dialog
never owns that figure IR and never reconstructs it in the GUI.

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
- active figure integration
- layout or gizmo integration
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
`procedures/__init__.py`.

For tables, the saved macro takes parameters naming the live kernel objects needed to
reopen the table.

For first-class figures, the saved macro is lowered from the authoritative figure IR
only. The dialog still stays thin: it receives a default name, requests bounded source
from the feature-owned figure save path, writes it into the macro block, and leaves all
figure semantics in the kernel-owned figure feature.

## Synchronization

Saving a macro must trigger the existing procedures reload path so the kernel rebuilds
its decorated macro registry and the GUI refreshes the relevant Windows submenu.

This same generic synchronization rule applies to both:

- `Windows -> Table Macros`
- future `Windows -> Graph Macros`

## Explicit Exclusions

- direct scientific execution from the dialog
- save-all-on-quit
- non-table saveable windows

## Future Work

- first-class figure integration using IR-backed recreation macros
- layout integration
- project-shutdown figure persistence that reuses the same IR-backed recreation source
- macro browser / rename / delete workflows
