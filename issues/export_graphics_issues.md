- [x] Slice 1: Make Kernel Transport Logging Authoritative For Hidden And Visible Commands
- [x] Slice 2: Bring Save Graphics Source Generation Up To Current Figure Patch Family Level
- [x] Slice 3: Trim Redundant Local Logging Around Figure Export Paths
- [x] Slice 4: Lock Export Graphics And Transport Logging With Behavior Tests And Present-Tense Docs

## Slice 1: Make Kernel Transport Logging Authoritative For Hidden And Visible Commands

### Type

`AFK`

### What to build

Move debug logging for GUI-originated Python dispatch into the shared
hidden/visible transport path so Hyde logs the final command string actually
sent to the kernel, regardless of which feature generated it. This slice should
leave current feature behavior intact while making transport logging the
authoritative source of truth for kernel-bound command visibility.

### Acceptance criteria

- [x] Hidden command dispatch logs the final command string at the transport
      layer.
- [x] Visible command dispatch uses the same logging policy.
- [x] The log window now shows dispatch activity for `Save Graphics...` even
      before export-specific source-generation cleanup is complete.
- [x] Existing manual state-local logging is not yet required to be removed, but
      transport logging is sufficient to observe all dispatched commands.

### Blocked by

None - can start immediately.

### User stories covered

- `issues/nonuniform_python_strings.md`: User stories 2, 3, 4, 10

## Slice 2: Bring Save Graphics Source Generation Up To Current Figure Patch Family Level

### Type

`AFK`

### What to build

Refit `Save Graphics...` so it stops inventing a dialog-local export lowering
path and instead works through the existing shared figure/matplotlib feature
plumbing at the same architectural level as `Remove from Graph...`. This slice
does not ask for a broader package-wide `python_source()` cleanup. It only asks
that export command construction stop living in dialog-local widget-to-string
code and instead live in the same figure-family command model as other
first-class figure operations.

### Acceptance criteria

- [x] `Save Graphics...` no longer generates its final export command directly
      from dialog-local widget state in the dialog class.
- [x] Shared figure/matplotlib feature plumbing owns the export-command
      lowering.
- [x] Figure-scoped export command generation is expressed through the existing
      figure-family command path rather than a one-off dialog-local lowering
      function.
- [x] `Save Graphics...` reaches parity with the current `Remove from Graph...`
      family level of reuse and feature-layer ownership.

### Blocked by

- Slice 1: Make Kernel Transport Logging Authoritative For Hidden And Visible Commands

### User stories covered

- `issues/export_graphics.md`: User stories 3, 4, 5, 23, 24
- `issues/nonuniform_python_strings.md`: User stories 6, 7, 8

## Slice 3: Trim Redundant Local Logging Around Figure Export Paths

### Type

`AFK`

### What to build

Clean up redundant feature-local manual logging in the export-adjacent figure
command paths now that transport logging is authoritative. This slice should
focus on the nearby figure export and figure patch surfaces, not the whole
package, and should leave the code closer to one logging rule rather than two
overlapping ones.

### Acceptance criteria

- [x] Nearby export-adjacent figure command paths no longer rely on manual
      logging shims solely to make dispatched commands visible in logs.
- [x] `Save Graphics...` and the current figure patch family follow one clear
      logging rule.
- [x] Removing redundant local logging does not reduce the observability of
      dispatched commands in the log window.
- [x] This cleanup remains local to export-adjacent figure command paths and
      does not broaden into a package-wide rewrite.

### Blocked by

- Slice 1: Make Kernel Transport Logging Authoritative For Hidden And Visible Commands
- Slice 2: Bring Save Graphics Source Generation Up To Current Figure Patch Family Level

### User stories covered

- `issues/nonuniform_python_strings.md`: User stories 2, 4, 9, 10

## Slice 4: Lock Export Graphics And Transport Logging With Behavior Tests And Present-Tense Docs

### Type

`AFK`

### What to build

Add the behavior-focused tests and present-tense documentation needed to lock
the new export and logging contract. The tests should verify the final
dispatched command and the log-observable behavior rather than helper wiring.
The docs should make clear that transport logging is authoritative and that
`Save Graphics...` now follows the current figure-family command path rather
than dialog-local lowering.

### Acceptance criteria

- [x] Tests cover transport-observable logging for hidden and visible dispatch.
- [x] Tests cover `Save Graphics...` preview/dispatch behavior through the new
      figure-family export command path.
- [x] Tests verify that export logging no longer depends on dialog-local or
      feature-local manual logging.
- [x] Present-tense docs describe the new export command path and logging
      contract without implying that `Do It` must rerun `python_source()` when
      it is already dispatching the authoritative generated preview string.

### Blocked by

- Slice 1: Make Kernel Transport Logging Authoritative For Hidden And Visible Commands
- Slice 2: Bring Save Graphics Source Generation Up To Current Figure Patch Family Level
- Slice 3: Trim Redundant Local Logging Around Figure Export Paths

### User stories covered

- `issues/export_graphics.md`: User story 25
- `issues/nonuniform_python_strings.md`: User stories 4, 9, 10, 11, 12
