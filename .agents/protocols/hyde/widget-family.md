# Hyde Widget Family Protocol

Shared contract for every Hyde widget-shape skill. Read this before creating or
normalizing a `HydeToolWidget`, `HydeDialogWidget`, or `HydeInteractiveWidget`.

## Required Reading

`AGENTS.md` already lists the required Hyde docs. Read them, then read only the
feature spec under `project_management/specs/<feature>/` and the code for the
surface you are changing.

## Widget Workflow

1. `add-hyde-ui-feature` writes or revises the spec
2. `grill-me` stress-tests the plan
3. `to-prd-and-issues` produces the PRD and the issue slices
4. pair the widget-shape skill with that issue work so the standard shape is
   captured before code exists
5. implement with `tdd` plus the widget-shape skill
6. `test-cleanup` converts red/green scaffolding into durable behavior tests

## IR Contract

This is the part most likely to be got wrong. `IR-CONTROL.md` is authoritative.

- Every widget base family owns one base-level IR slot named `widget_ir`.
  `HydeInteractiveWidget.widget_ir` is the live current object IR.
  `HydeDialogWidget.widget_ir` and `HydeToolWidget.widget_ir` are their own IRs
  and may hold imported snapshots used to build previews or commands.
- All GUI-generated command Python comes from `HydeIR.python_source()`. A widget
  must not assemble command strings locally, and preview text is that same
  generated string.
- `HydeIRDiff` is a `HydeIR` subclass used for change-oriented lowering.
- Module placement:
  - package-owned IR: `hyde/features/<package>_ir.py`
  - package-pure lowerers: `hyde/features/<package>_features.py`
  - widget workflow IR composing several package IRs: plugin-local `<widget>_IR.py`
- `hyde/user_interface/shared/` is neutral scaffolding only. Concrete feature
  authority never lives there.

## Ownership Split

`HydeIR` owns local edit-session state, validation, deterministic mutation
semantics, typed normalized state access, orchestration across package-pure
lowerers, and lowering through `python_source()` / `macro_source()`.

`<package>_features.py` owns package-local string lowering **only**. It carries no
IR authority and no cross-package orchestration. Do not put validation or state
normalization there.

The kernel owns authoritative scientific objects, values, and runtime identity.

The widget owns Qt wiring, transient selection and focus state, action
construction, user-facing warnings and confirmations, dispatch decisions, and its
own `widget_ir`.

## Override Discipline

Keep a subclass override only when it adds real local policy.

Delete overrides that only restate base behavior, forward to a shared helper under
a new name, duplicate base-owned plumbing, or maintain a second copy of state the
base already holds. `AGENTS.md` forbids trivial pass-through wrappers: make the
shared helper the actual interface instead.

## Placement Rules

- Static layout belongs in `.ui` files. Python supplies signal wiring, dynamic
  row/item creation, state synchronization, and genuinely runtime-only widgets.
- Plugin package names follow the `STYLE.md` suffix taxonomy: `*_tool`,
  `*_interactive`, `*_dialog`, no suffix for infrastructure.
- Kernel-side code must not import `hyde.user_interface.plugins` or Qt.

## Tests

Prove observable behavior, not wiring. A test should fail when a user-visible
contract breaks or when a declared architectural boundary is crossed. Do not
assert helper identity, private call order, or import shape.

## Output Rules

Keep the patch small and local to the plugin unless the base class clearly needs a
small shared improvement. Update the relevant spec when the contract changes, and
update the base-widget tests when the shared contract changes.
