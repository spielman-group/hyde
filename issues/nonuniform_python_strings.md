## Problem Statement

Hyde still does not follow one uniform package-wide rule for GUI-originated
Python generation. The intended rule is now stricter and explicit:

- Every GUI-generated Python string must come from a `python_source()` family
  path owned by `HydeGuiState`.
- `Do It` does not need to rerun `python_source()` if it dispatches the exact
  preview string already generated from that state object.

The current package is still mixed. Some plugin families already use
`HydeGuiState` correctly or acceptably. Others still bypass the rule by calling
codec methods directly, assembling helper strings in widgets/windows/dialogs, or
relying on figure-family helper paths with no `HydeGuiState` owner.

This inconsistency is now the package-level problem, not just an export-graphics
problem. Hyde should move to one standard command-generation solution across the
whole GUI, with no exceptions.

## Solution

Standardize the entire Hyde package on one command-generation contract:

- all GUI-generated Python comes from `HydeGuiState.python_source()`
- widgets/dialogs/windows stop building Python directly
- direct GUI calls to `FeatureCodec.state_to_python(...)` stop being public GUI
  behavior paths
- where current `HydeGuiState` or shared widget bases are insufficient, extend
  those shared bases instead of creating feature-local bypasses
- `HydeFileDialog` subclasses should use the shared preview/generation/dispatch
  path defined by `HydeFileDialog`, adding behavior by overriding hooks and
  calling `super()` rather than inventing alternate submission paths

The cleanup should begin with a package-wide documentation pass and a complete
inventory of current Python-generation paths, then proceed family by family
until the entire GUI is on the same state/codec path. The expectation is that
this will simplify Hyde by collapsing multiple ad hoc command-generation shapes
back into one standard solution.

## Key Requirements

- every GUI-generated Python string has one authoritative `HydeGuiState`
  owner
- preview text and execution use the same `python_source()` output
- cached preview dispatch is allowed
- direct GUI calls to codec lowering and direct string assembly disappear from
  feature code
- `HydeFileDialog` subclasses extend the shared path through overrides and
  `super()`, not alternate submission paths
- the final system has no GUI command-generation exceptions and the docs match
  the implemented design

## Scope Notes

- The package-wide rule is now strict: GUI-generated Python must originate from
  a `HydeGuiState` `python_source()` family path. No exceptions are intended.
- The intended API surface is one generation method: `python_source()`.
- Preview should display the string produced by `python_source()` rather than a
  second preview-only generation method.
- Cached preview dispatch is acceptable. The contract is about where the string
  is generated, not about rerunning `python_source()` on `Do It`.
- Direct GUI calls to codec `state_to_python(...)` are violations of the target
  architecture.
- Direct string assembly in widgets, dialogs, windows, menus, and runtime
  helpers is a violation of the target architecture.
- If existing use cases do not fit the current `HydeGuiState` surface, the
  solution is to extend shared state/base infrastructure narrowly, not to add
  feature-local bypasses.
- `HydeFileDialog` is a specific architectural constraint:
  - subclasses should use the shared generation/submission path already defined
    by `HydeFileDialog`
  - specialization should happen by overriding hook methods and calling `super()`
    as needed
  - custom alternate command-generation or submission paths in subclasses are
    violations unless the shared base is first extended to support the case

## Known Noncompliant Families

- shared figure-dialog patch generation
- figure-window refresh and regenerate paths
- figure and table shortcut helpers that still lower directly for GUI callers
- Curve Fit mixed helper/state command paths
- any remaining tails found by the package-wide inventory slice

## Testing Decisions

- Good tests should verify the externally visible contract:
  - what string is previewed
  - what string is dispatched
- Tests should avoid asserting incidental helper names, local debug labels,
  codec call structure, or direct implementation choreography when the same
  defect can be caught through preview text or dispatched text.
- Cached preview dispatch remains acceptable. Tests should verify that the
  dispatched string matches the authoritative generated preview string, not that
  `python_source()` was rerun.
- Tests should assume that preview text comes from `python_source()` itself, not
  from a separate preview-generation API.
- Shared-base tests should cover `HydeGuiState` and `HydeFileDialog` contracts
  where those contracts are extended to support remaining real use cases.

## Out of Scope

- Redesigning Hyde’s public kernel API
- Changing the semantic meaning of public Hyde commands
- Requiring `Do It` to rerun `python_source()` when it is already dispatching the
  exact generated preview string
- Keeping long-term exceptions to the single `HydeGuiState` command-generation
  rule
- Solving the entire package in one unstructured patch without inventory and
  family-by-family migration

## Further Notes

- This is now a package-wide simplification effort, not a one-feature cleanup.
- The work should reduce Hyde complexity by collapsing multiple ad hoc
  command-generation patterns into one standard state/codec solution.
