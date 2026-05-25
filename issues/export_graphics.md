## Problem Statement

Hyde has first-class figure windows and a documented `Save Graphics...` action in the
figure workflow, but it does not yet provide a Hyde-native export dialog for writing
the active figure to standard graphics formats. Users need a figure-scoped export
surface that uses the live kernel `Figure` as the source of truth, exposes Hyde's
standard preview-backed dialog footer, and integrates naturally with the shared file
selection machinery rather than relying on an ad hoc export path.

The user-facing problem is not only "save this figure to disk." The export workflow
must also feel like a normal Hyde dialog, must live in the `Figure` menu and matching
figure context menu, must default into a project-local export area, and must present
format, size, DPI, and transparency options in a clear way that does not turn the GUI
into an owner of scientific state.

There is also a code-shape problem behind the feature. The export-option machinery
implemented for `Save Graphics...` is expected to be reused later for figure copying
through `Copy...` or keyboard copy workflows. That copy feature is not part of this
scope, but the export abstractions chosen here must not entangle general graphics
output options with file-only assumptions.

## Solution

Introduce a `Save Graphics` dialog as a figure-scoped `HydeFileDialog` subclass that
opens from the `Figure` menu and matching figure context menu for the active
first-class figure. The dialog uses a full embedded Hyde file browser at the top,
defaults into a project-local `exports/` directory, and presents a two-part export
configuration area below it:

- a runtime-derived format list with user-facing labels
- a general export-options panel that initially contains `DPI` and `Transparent`
- a separate size section with `Same` and `Custom` modes in inches

The dialog remains a standard `HydeDialogWidget` surface:

- the lower pane shows the executable backing string when a concrete target path is
  available, otherwise validation or status text
- `Do It`, `To Cmd Line`, and `To Clip` all operate on that same backing string
- `Help` remains visible but inert in the initial deployment

The export source of truth is always the live kernel matplotlib `Figure` for the
opening first-class figure window. The dialog does not export from cached pixels, does
not mutate figure IR, and does not introduce a file-specific helper when ordinary
matplotlib save semantics are sufficient after resolving the figure.

The implementation should also isolate general graphics-output option lowering from
file-target details so the future figure-copy workflow can reuse the same format/size/
DPI/transparency machinery without inheriting file-path policy.

## User Stories

1. As a Hyde user, I want `Save Graphics...` in the `Figure` menu, so that figure
   export lives with other figure actions rather than in a generic file menu.
2. As a Hyde user, I want the figure window context menu to expose the same
   `Save Graphics...` action, so that the menu and context-menu workflows stay aligned.
3. As a Hyde user, I want the dialog to be scoped to the active first-class figure,
   so that I export the figure I am currently working on without choosing from a
   second figure picker.
4. As a Hyde user, I want the dialog to use Hyde's normal preview-backed footer, so
   that `Do It`, `To Cmd Line`, and `To Clip` behave like other Hyde dialogs.
5. As a Hyde user, I want the lower pane to show the actual executable export string
   when a concrete target path exists, so that I can inspect the exact export command.
6. As a Hyde user, I want the top of the dialog to contain a full embedded file
   browser, so that choosing the export target feels like a real save workflow.
7. As a Hyde user, I want export to default into a project-local `exports/`
   container, so that graphics land in a predictable project area by default.
8. As a Hyde user, I want Hyde to create that default `exports/` directory when the
   dialog opens if needed, so that Hyde's suggested default target is immediately
   usable.
9. As a Hyde user, I want the default basename to come from the stable figure name,
   so that exports are named consistently with Hyde's figure identity.
10. As a Hyde user, I want the format list to show every output format matplotlib
    reports in the current runtime, so that Hyde does not hide formats that are
    actually available on my system.
11. As a Hyde user, I want `pdf` preferred first and `png` second when available, so
    that the default ordering matches common export workflows without inventing a
    fully curated Hyde subset.
12. As a Hyde user, I want the selected format to drive the file browser's active
    filter and the recommended filename suffix, so that the target path and format do
    not drift apart.
13. As a Hyde user, I want Hyde to respect a deliberate custom extension such as
    `.jpeg`, so that automatic suffix management does not overwrite intentional file
    naming choices.
14. As a Hyde user, I want `DPI` available with a default of `300`, so that I can
    control export resolution directly.
15. As a Hyde user, I want `Transparent` visible when supported and disabled when it
    clearly is not, so that the dialog stays stable without promising impossible
    behavior.
16. As a Hyde user, I want `Same` and `Custom` size modes in inches, so that I can
    either export the current figure size or override it explicitly.
17. As a Hyde user, I want the disabled size fields under `Same` to show the size
    that would be used right now, so that I can see the actual export dimensions even
    without switching to `Custom`.
18. As a Hyde user, I want switching to `Custom` to start from the current figure
    size, so that I edit a meaningful baseline instead of blank fields.
19. As a Hyde user, I want overwrite handling to use Hyde's normal confirmation flow
    rather than an extra force-overwrite toggle, so that save behavior stays simple.
20. As a Hyde user, I want the dialog to reset to standard defaults each time it
    opens, so that initial export behavior is predictable and not dependent on hidden
    remembered state.
21. As a Hyde developer, I want the dialog to subclass `HydeFileDialog`, so that the
    export workflow reuses Hyde's shared file-selector family rather than building a
    one-off top section.
22. As a Hyde developer, I want `HydeDialogWidget` to support stacked user-content
    rows, so that file-driven dialogs can combine an embedded file browser with
    additional feature-specific controls below it.
23. As a Hyde developer, I want general graphics-output option lowering to stay
    separable from file-path handling, so that future figure-copy work can reuse the
    same option machinery without inheriting file-only abstractions.
24. As a Hyde developer, I want export to prefer direct matplotlib save semantics
    once the figure is resolved, so that Hyde does not invent unnecessary public
    helpers for straightforward export behavior.
25. As a Hyde tester, I want behavior-focused tests around menu exposure, default
    file targeting, preview payloads, format coupling, size modes, and dispatch, so
    that regressions are caught at the user-visible contract level.

## Implementation Decisions

- `Save Graphics...` is a figure-scoped action surfaced in both the `Figure` menu and
  the figure window context menu. It appears in a new menu section below the current
  figure items, separated from the existing group.
- The dialog title is `Save Graphics`.
- The dialog is a `HydeFileDialog` subclass rather than a bespoke `HydeDialogWidget`
  subclass.
- `HydeDialogWidget` should be extended minimally so content can be mounted into
  stacked body rows while the standard preview pane and footer remain in the final
  row.
- `HydeFileDialog` should use that stacked-content capability so its embedded
  `HydeFileWidget` can occupy the top row while export-specific controls occupy rows
  below it.
- The file browser is the full embedded `HydeFileWidget`, not a compact row plus a
  secondary modal browser.
- `HydeFileWidget` / `HydeFileDialog` should support a reusable option that creates
  the suggested directory when the dialog opens; this defaults to `False` generally
  and is enabled for `Save Graphics`.
- The default export location is the current project's `exports/` container. The
  project package should also carry that container as part of the default package
  shape.
- The default basename derives from the stable Hyde figure name and is sanitized for
  filesystem safety only as needed.
- The dialog does not constrain users to save only inside the default `exports/`
  directory.
- The format list is runtime-derived from matplotlib's currently supported save
  formats. The ordering is `pdf` first when available, `png` second when available,
  and the remaining formats alphabetized.
- The default selected format is the first available format in that ordered list.
- The dialog shows user-facing format labels while preserving the corresponding
  matplotlib format keys internally.
- Selected format is authoritative for:
  - the backing export format
  - the embedded file browser's active name filter
  - Hyde-managed filename suffix recommendation
- Hyde rewrites the filename suffix only when Hyde is still managing that suffix, not
  when the user has deliberately entered a different valid variant such as `.jpeg`.
- The format section is a two-column surface: a single-selection format list on the
  left and a general options panel on the right. The initial options are `DPI` and
  `Transparent`, but the panel should be shaped to accept future format-related
  options without reworking the layout contract.
- `DPI` remains active for all formats and defaults to `300`.
- `Transparent` defaults to off and remains visible, but is disabled when the chosen
  format/backend clearly does not support it.
- The size contract is inches-only in the initial deployment. Hyde may add other
  units later, but there is no units chooser in this scope.
- The size controls use `Same` and `Custom`. Width and height are always visible and
  reflect the values that would be used if `Do It` were pressed immediately.
- Under `Same`, width and height are disabled and display the current figure size in
  inches for the modal session.
- Switching to `Custom` initializes width and height from that current figure size.
  Switching formats does not reset custom size.
- Overwrite behavior uses the shared confirmation flow on `Do It`; there is no
  `Force Overwrite` checkbox.
- `Help` stays visible but inert in the initial deployment.
- The backing export string should use direct matplotlib save semantics on the
  resolved figure, not a dedicated `hyde.save_graphics(...)` helper.
- The general graphics output option model chosen here should be reusable by future
  figure-copy workflows such as `Copy...` or keyboard copy operations. That future
  copy feature is out of scope, but the abstractions introduced for size, format, DPI,
  and transparency should not be coupled to file-only behavior.

## Testing Decisions

- Good tests should verify observable behavior rather than implementation shape.
  Relevant behavior includes menu exposure, dialog availability from the figure
  workflow, default target path construction, suggested-directory creation, preview
  payload generation, format ordering, format/filter/suffix coupling, size-mode
  semantics, transparency enablement, overwrite confirmation, and execution dispatch.
- Tests should avoid asserting incidental layout plumbing, row indices, helper call
  ordering, or widget-internal signal choreography when the same defect can be caught
  through visible behavior.
- The shared dialog-base changes should be tested through behavior that matters to
  consumers: multiple body rows render correctly, `HydeFileDialog` still works, and
  project file dialogs remain intact after the base-class extension.
- The `Save Graphics` dialog should be tested against the exported payload and user
  contract:
  - it binds to the opening first-class figure
  - it targets the live kernel figure rather than cached GUI pixels
  - `Do It`, `To Cmd Line`, and `To Clip` use the same backing string when a concrete
    path exists
  - validation/status text replaces the payload when a concrete path does not exist
- The format-ordering and suffix-management tests should be written so they would
  catch regressions in runtime format handling without hard-coding every internal
  detail of the list-building logic.
- The general graphics-output option abstraction should be tested at its public
  contract boundary so future copy/export reuse remains protected by behavior tests.
- Prior art should come from the existing `HydeDialogWidget`-family dialog tests, the
  new shared file-dialog tests already introduced for the file widget family, and the
  existing figure dialog tests that verify preview-backed hidden-command behavior.

## Out of Scope

- Figure copying through `Copy...`, keyboard copy shortcuts, or clipboard-targeted
  graphics export
- Batch export
- A monochrome or grayscale export contract
- Dialog-memory persistence across openings
- Exporting non-first-class figures through Hyde's figure workflow
- Curating or restricting matplotlib's runtime export format list beyond the agreed
  `pdf` / `png` ordering preference
- Replacing the embedded Qt browser with a custom Hyde-built file browser
- Changing the authoritative source of figure truth away from the live kernel figure

## Further Notes

- The current screenshot artifact was useful for layout direction, but the final Hyde
  contract intentionally diverges from that source in several places, including menu
  placement, the standard Hyde footer contract, the removal of recommended-format and
  color controls, the embedded full file browser, and the simplified overwrite model.
- This feature is both a user-facing export dialog and a code-shape decision point
  for future graphics-copy work. The implementation should therefore separate
  file-target policy from reusable graphics output option lowering wherever the extra
  indirection pays for itself clearly.
- The initial deployment should stay narrow and predictable: one figure, one file
  target, one standard Hyde dialog contract, and no remembered per-dialog state.
