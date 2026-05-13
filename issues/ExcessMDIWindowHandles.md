**TRD: Replace Hyde Window Handle Semantics With Qt `objectName()`**

## Problem Statement

Hyde currently uses “handle” language and parallel window-identity behavior in some
MDI code. Hyde should not keep a separate window-handle concept. The stable identity
and behavior currently associated with window handles should be replaced by Qt's
existing `QMdiSubWindow.objectName()`.

## Solution

Refactor Hyde’s MDI window identity model so that `QMdiSubWindow.objectName()` is the
single stable identifier for ordering, lookup, session workspace identity, and any
other current generic window-handle behavior.

Window titles remain presentation text only. They are derived from the stable
`objectName()` and may append additional descriptive suffix text without changing MDI
identity.

## User Stories

1. As a Hyde developer, I want MDI window identity to use Qt’s built-in
   `objectName()`, so that Hyde does not maintain a parallel window-handle concept.
2. As a Hyde developer, I want table, figure, and tool windows to participate in
   shared MDI behavior through the same identity mechanism, so that ordering and
   restore code stays generic.
3. As a Hyde developer, I want tables and figures to generate their stable MDI names
   through one shared code path, so that the `TableN` and `FigureN` patterns stay
   aligned.
4. As a Hyde maintainer, I want generic “handle” terminology removed from MDI code,
   so that future window persistence work is easier to reason about.
5. As a Hyde user, I want no visible behavior change from this refactor, so that
   existing project workflows remain stable.

## Implementation Decisions

- Use `QMdiSubWindow.objectName()` as the authoritative stable identity for Hyde MDI
  windows.
- Do not preserve a parallel generic window-handle concept. Existing window-handle
  behavior is superseded by `objectName()`.
- Tool windows use their existing MDI contribution keys as `objectName()`.
- Tables and figures share one naming path that generates stable names with `Table`
  and `Figure` prefixes respectively.
- The generated table or figure name is assigned to the subwindow `objectName()`.
- The window title is derived presentation text. It begins with `objectName()` and may
  append `": ..."` detail text. Lookup, ordering, and persistence never depend on the
  title text.

## Testing Decisions

- Tests should prove observable MDI behavior, not internal naming choreography.
- Add or update tests showing that mixed MDI window ordering can be captured and restored using `objectName()`.
- Add tests covering tool, table, and figure windows participating in the same identity/order path.
- Add tests showing that table and figure titles may append extra descriptive text
  while `objectName()` remains the stable identity.
- Avoid tests that only assert helper call order or private implementation details.

## Out of Scope

- Changing public table restore syntax such as `target=...`, unless a separate API decision is made.
- Changing scientific state ownership, figure IR, table data semantics, or kernel restore behavior.
- Changing the minimized/maximized geometry persistence model except where it consumes MDI identity.
- Adding compatibility shims for old internal terminology.
- Adding richer appended table/figure title text beyond the identity prefix.

## Further Notes

This is a cleanup/refactor TRD. 
