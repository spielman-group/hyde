## Problem Statement

Hyde's current first-class figure system uses two GUI-to-kernel mutation channels:
explicit Python for figure creation-oriented flows and a separate semantic action
transport for routine figure editing. That split has introduced duplicated logic,
post-hoc exceptions, and figure-specific hacks that do not match Hyde's broader
command-driven modality.

From the user's perspective, figure edits should behave like the rest of Hyde:
clicking `Do It`, using live update, or sending a command to the command line should
all correspond to ordinary Python that a user could type manually and get the same
final result. Today that is not true for first-class figure editing.

## Solution

Move first-class figure mutation back onto one canonical Python ingress path.

GUI figure editing continues to use the existing dialogs, but those dialogs stop
driving figure changes through a separate semantic action channel. Instead they emit
minimal standard-matplotlib patch blocks. The only Hyde-specific emitted primitive is
figure lookup, for example `hyde.get_figure("Figure0")`; the actual edits after that
are ordinary matplotlib calls. These emitted blocks should go through Hyde's normal
Python execution path, so hidden figure-edit commands appear in the existing Hyde
debug logging just like other hidden Hyde commands. This is not a new special
communication mechanism; it is reuse of Hyde's ordinary Python-command interface.

The intended logging channel is the same hidden-command debug stream that already
shows entries such as:

```text
2026-05-22 12:47:32,422 DEBUG hyde: [Hyde state] SaveProjectState
state:
{'command': 'save_project',
 'feature': 'hyde_command',
 'items': [],
 'settings': {'load': True,
              'mode': 'save',
              'overwrite': False,
              'project_dir': None},
 'state_version': 1,
 'ui': {}}
python:
hyde.save_project(mode='save')
```

Figure-edit commands should appear through that same logging path, with the emitted
hidden Python block visible there for debugging.

On the kernel side, Hyde's matplotlib backend becomes responsible for keeping
first-class figure IR synchronized with live matplotlib objects. Dirty tracking uses
matplotlib's native stale/change propagation. After each completed top-level Python
execution block, Hyde resyncs only dirty first-class figures, rebuilds the full
supported semantic IR from the live figure object graph, batches snapshot updates
back to the GUI, and degrades gracefully when the live figure contains unsupported
features.

## User Stories

1. As a Hyde user, I want clicking `Do It` on a figure dialog to execute ordinary Python, so that figure editing follows the same mental model as the rest of Hyde.
2. As a Hyde user, I want `To Cmd Line` to emit the same code that `Do It` uses, so that visible and hidden execution remain equivalent.
3. As a Hyde user, I want live update to use the same mutation path as final commit, so that Hyde does not have separate temporary and permanent figure behaviors.
4. As a Hyde user, I want figure-edit commands to use standard matplotlib calls, so that the emitted code is readable and familiar.
5. As a Hyde developer, I want hidden figure-edit commands to appear in Hyde's existing debug logging window, so that figure editing uses the normal command execution interface rather than a side channel.
6. As a Hyde user, I want `hyde.get_figure("Name")` to give me the live first-class figure, so that I can edit it from the command line using normal matplotlib.
7. As a Hyde user, I want `plt.figure("Figure1")` creation names and Hyde figure names to be the same truth, so that identity is not split across two fields.
8. As a Hyde user, I want figure label changes to act as real renames, so that figure naming behaves consistently between matplotlib and Hyde.
9. As a Hyde user, I want rename collisions to fail cleanly, so that figure identity never becomes ambiguous.
10. As a Hyde user, I want Hyde to resync figure state after a completed Python block, so that command-line edits and GUI edits stay in sync automatically.
11. As a Hyde user, I want Hyde to resync only figures that actually changed, so that large sessions with many open figures remain responsive.
12. As a Hyde developer, I want dirty tracking to rely on matplotlib-native change propagation, so that Hyde avoids a large, brittle wrapper layer over matplotlib classes.
13. As a Hyde developer, I want backend resync to rebuild the full supported semantic IR for a dirty first-class figure, so that Hyde has one coherent imported state after each execution block.
14. As a Hyde developer, I want post-block resync to run even after exceptions, so that partially successful figure mutations are still reflected in Hyde state.
15. As a Hyde user, I want unsupported matplotlib features to keep the figure live instead of breaking it out of Hyde, so that ordinary command-line experimentation remains possible.
16. As a Hyde user, I want the title bar to indicate `[Unsupported Feature]` when Hyde cannot fully represent the live figure, so that the current limitation is visible.
17. As a Hyde user, I want supported dialogs to keep working on the supported subset of an otherwise unsupported figure, so that one unsupported edit does not disable all figure tooling.
18. As a Hyde user, I want project save/session save to warn when a figure is unsupported but still recreate what Hyde can, so that windows do not silently vanish on reload.
19. As a Hyde user, I want save/reopen behavior for unsupported figures to use only the supported-subset matplotlib code, so that Hyde does not invent untrustworthy recreation source.
20. As a Hyde user, I want `Cancel` during live update to restore the opening state of the dialog-owned region, so that interactive editing remains reversible.
21. As a Hyde developer, I want the current figure dialogs to remain the canonical UI surfaces, so that this cleanup changes the mutation architecture without forcing a product redesign.
22. As a Hyde developer, I want backend-to-GUI figure snapshot updates to be batched per completed Python block, so that GUI refresh stays coherent and avoids churn.
23. As a Hyde developer, I want first-class and non-first-class figures to remain distinct in this effort, so that this cleanup stays focused on Hyde-owned figure windows.
24. As a Hyde developer, I want the current figure action/session transport to stop being the primary architecture, so that Hyde no longer maintains duplicate mutation mechanisms for figures.

## Implementation Decisions

- Figure mutation for first-class figures should have one canonical ingress path:
  emitted Python blocks that use standard matplotlib calls after a Hyde figure lookup.
- Those emitted hidden Python blocks should use Hyde's existing Python execution and
  logging interface, so figure-edit commands appear in the normal Hyde debug log
  stream rather than on a separate transport.
- The intended logging channel is the existing `[Hyde state] ...` hidden-command
  debug output that already shows hidden commands such as `hyde.save_project(...)`.
  Figure-edit commands should appear there too.
- Figure creation continues to use `plt.figure(...)`; existing figure lookup uses a
  Hyde primitive such as `hyde.get_figure(<canonical_name>)`.
- The canonical figure identity is the figure label/name used at creation and on later
  rename operations. Hyde should not maintain a second conflicting identity field.
- Rename collisions fail and restore the previous valid canonical name.
- Existing figure-edit dialogs remain in place as the canonical UI surfaces.
- Those dialogs should populate controls from the imported kernel-owned figure IR
  snapshot, not by directly walking live matplotlib objects.
- `Do It`, live update, and `To Cmd Line` all use the same canonical matplotlib patch
  block.
- Figure-edit command emission should be minimal-patch oriented: only actually
  changed features are changed.
- Live update cancel/rollback uses the same Python ingress path by emitting a bounded
  rollback patch for the dialog-owned region.
- The backend should not depend on a broad forest of Hyde-specific wrappers around
  matplotlib classes for routine dirty tracking.
- Dirty tracking for first-class figures should use matplotlib-native stale/change
  propagation as the primary signal.
- After any completed top-level Python execution block, Hyde should resync only dirty
  first-class figures.
- That post-block resync rule applies across Hyde execution paths, including visible
  terminal commands, hidden GUI commands, procedures execution, and restore code.
- Resync should also run after execution blocks that end in exceptions.
- Backend resync rebuilds the full supported semantic IR from the live matplotlib
  object graph for each dirty first-class figure.
- Unsupported live structure should keep the figure first-class while marking the
  figure unsupported/incomplete and preserving only the supported semantic subset in
  imported IR.
- The GUI should show an explicit unsupported-feature warning in the figure window
  chrome when a live figure cannot be fully represented.
- Saving unsupported figures should warn and recreate the supported subset only.
- GUI snapshot updates for dirty figures should be batched per completed execution
  block rather than streamed piecemeal.
- The current figure edit session/action transport is expected to shrink
  substantially or cease to be the primary mutation path once the command-driven
  backend resync model is in place.

## Testing Decisions

- Good tests should verify externally meaningful behavior and architectural contract,
  not incidental helper structure.
- Tests should prove that visible terminal commands, hidden GUI commands, and dialog
  actions converge on the same first-class figure state after backend resync.
- Tests should verify that hidden figure-edit commands are observable through Hyde's
  normal debug logging path rather than a figure-specific side channel.
- Tests should verify that only dirty first-class figures resync after block
  completion.
- Tests should verify that resync occurs after exceptions when live figure state has
  partially changed.
- Tests should verify rename behavior, including successful rename propagation and
  failure-on-collision restoration.
- Tests should verify unsupported-feature detection, title-bar warning behavior, and
  supported-subset editing/save behavior.
- Tests should verify that `Do It`, live update, `Cancel`, and `To Cmd Line` all use
  one canonical emitted matplotlib patch path for the covered dialogs.
- Tests should cover axis editing, trace appearance editing, and Curve Fit attached
  display under the new command-driven model.
- Prior art should come from existing Hyde tests around first-class figure windows,
  figure snapshot/update behavior, axis and trace dialogs, and Curve Fit attached
  display workflows.

## Out of Scope

- Automatic promotion of non-first-class matplotlib figures into Hyde first-class
  windows.
- Broader redesign of the existing figure-related dialogs or window surfaces.
- New figure-edit product surfaces beyond the current dialogs.
- Multi-subplot/GridSpec semantic expansion beyond what the importer currently
  supports.
- General-purpose matplotlib compatibility for every possible artist type in one pass.
- Replacing backend refresh traffic with explicit Python when no user-triggered
  mutation is involved, such as resize-driven redraw updates.

## Further Notes

- This cleanup is intentionally about removing hack-like duplication between figure
  communication channels, not about broad UI redesign.
- The central architecture change is moving figure mutation back to one Python
  ingress path while letting the backend own synchronization from live matplotlib
  objects back into Hyde IR.
- Unsupported-feature handling should degrade honestly and visibly rather than hiding
  limitations behind stale or fabricated recreation state.
