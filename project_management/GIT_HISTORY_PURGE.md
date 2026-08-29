# Git History Purge: Removing Igor-Derived Spec Material

Runbook for permanently removing Igor Pro source material from
`spielman-group/hyde`, including all past commits.

**Status: EXECUTED 2026-08-29. History has been rewritten and force-pushed.**

The rewrite is done. What remains is the GitHub-side garbage collection in
step 6 — until GitHub confirms it, the old objects are still reachable by
direct SHA URL, and the purge is not complete.

## Execution record

| Check | Result |
| --- | --- |
| Paths purged | 58 (23 `specifications/`, 8 `IGOR.md`, 27 screenshots) |
| Commits preserved | 191 / 191 |
| Refs preserved | 7 / 7 |
| `SPEC.md` files preserved | 17 |
| Content mismatches on surviving files | 0 |
| Remote size | 21M -> 2.3M |

Verified against a fresh clone of the remote, not local state. All local
branches were reset to the rewritten refs, the stale
`.claude/worktrees/brave-chaplygin-99255e` worktree was removed after
confirming it held no unique content, and the local object store was expired
and repacked (23M -> 2.0M).

Pre-rewrite backup: `~/hyde-backup-prerewrite.git` (191 commits). Keep it until
GitHub confirms garbage collection, then it may be deleted.

Anyone holding a clone made before 2026-08-29 must delete it and re-clone. A
single push from such a clone restores the purged blobs.

## Motivation

The feature-spec tree contains material copied verbatim from WaveMetrics' Igor
Pro documentation:

- eight `IGOR.md` files (~930 lines of verbatim Igor Pro help prose)
- 50 PNG screenshots of the Igor Pro user interface, across two historical
  locations

The repository is **public**, so this material is currently published. Deleting
it from `HEAD` is not sufficient — every blob stays retrievable from history.

## Decided scope: split spec inputs from spec outputs

A feature spec has *inputs* (vendor screenshots, vendor documentation) and an
*output* (`SPEC.md`, written by this project). Only the inputs are third-party
material. The repository is therefore structured so the two never mix:

```
project_management/specs/<feature>/
├── SPEC.md            # Hyde-authored. Tracked and public.
└── _source/           # Third-party input material. Gitignored, local only.
    ├── IGOR.md
    └── *.png
```

Purged from history: all 58 paths listed in `purge-paths.txt`.
Retained: every `SPEC.md`, `IPC_PROTOCOL.md`, and
`procedure_browser/reference_docs.md`.

Because `_source/` is gitignored, no future spec input can be committed by
accident, and this cleanup should never need repeating.

## Already done (working tree only, not yet committed)

- Source material moved into per-feature `_source/` directories (32 files).
- `.gitignore` set to `project_management/specs/*/_source/`.
- `SPEC.md` image links repointed at `_source/`.
- `purge-paths.txt` generated — the exact, verified list of paths to purge.

`.gitignore` does **not** untrack already-tracked files. The moves currently
show as unstaged deletions of the old paths; committing them removes the
material from `HEAD`. The history rewrite is what removes it from the past.

## Preconditions — do not start until all of these hold

1. **The working-tree changes above are committed and pushed.** The rewrite
   operates on what is already on the remote.
2. **No in-flight work anywhere.** A rewrite invalidates every existing clone.
   Anyone who pushes from a pre-rewrite clone silently restores the purged
   blobs and undoes the whole operation. At the time of writing another worker
   has active work here; that must be finished and stopped first.
3. **All feature branches merged or abandoned.** Eight local and six remote
   branches exist; every rewritten branch must be force-pushed.
4. **`.claude/worktrees/` removed** with `git worktree remove`. Linked worktrees
   reference object SHAs that will cease to exist.
5. **Branch protection lifted on `master`** for the duration of the force-push.
6. **A verified backup exists** (step 2).

## The two-location trap

The spec material has lived at **two** paths. It began at a top-level
`specifications/` directory and was later moved under
`project_management/specs/`. A filter scoped only to the current location
silently leaves all 23 original files in history.

This is easy to get wrong. While preparing this plan, a first attempt at the
enumeration used the pattern `^(specifications/|...)$`, where the anchored
first alternative matched nothing — producing a list of 35 paths that looked
plausible and omitted every file from the original location. **Always check the
per-location counts, not just the total.** The correct list is:

| Source | Count |
| --- | --- |
| `specifications/` (22 PNGs + `UI_SPEC.md`) | 23 |
| `project_management/specs/*/IGOR.md` | 8 |
| `project_management/specs/*/*.png` | 27 |
| **Total** | **58** |

Two historical feature directories no longer present at `HEAD`
(`data_browser/`, `command_window/`) are included; they still hold blobs.

`specifications/UI_SPEC.md` is Hyde's own early writing, not vendor material.
It is included in the purge because the whole directory is long dead and
superseded by the per-feature `SPEC.md` files. Drop that one line from
`purge-paths.txt` if you would rather keep it in history.

`project_management/snapshots/hyde_phase2_execution_prototype.png` is Hyde's
own screenshot and is **not** in scope.

Regenerate and re-verify the list immediately before running:

```bash
git log --all --format="" --name-only \
 | grep -E "^(specifications/.+|project_management/specs/.*/(IGOR\.md|[^/]*\.png))$" \
 | sort -u > purge-paths.txt
wc -l < purge-paths.txt                        # expect 58 (plus any new commits)
grep -c '^specifications/' purge-paths.txt     # expect 23 — must not be 0
```

## Scale

- 184 commits across all branches; **64 touch the affected paths**
- 0 tags, 0 forks, 0 stars, 0 open pull requests
- 19 closed issues (these live outside git and survive a rewrite)

Every commit from the first affected commit onward gets a new SHA.

## Procedure

### 1. Install tooling

`git-filter-repo` is not currently installed. Do not use `git filter-branch`;
it is far slower and much easier to get wrong.

```bash
brew install git-filter-repo
```

### 2. Take a backup

```bash
git clone --mirror https://github.com/spielman-group/hyde ~/hyde-backup-prerewrite.git
git -C ~/hyde-backup-prerewrite.git rev-list --all --count
```

Keep this until the purge is confirmed good. It is the only way back.

### 3. Rewrite on a fresh mirror clone

`git-filter-repo` expects a fresh clone; run it there, not in the working repo.

```bash
git clone --mirror https://github.com/spielman-group/hyde /tmp/hyde-rewrite.git
cd /tmp/hyde-rewrite.git
git filter-repo --invert-paths --paths-from-file /path/to/purge-paths.txt
```

`--paths-from-file` treats each line as a literal path, which avoids the glob
ambiguity around whether `*` crosses a `/` separator.

### 4. Verify before pushing

```bash
# must print nothing
git log --all --format="" --name-only \
 | grep -E "^(specifications/|project_management/specs/.*(IGOR\.md|\.png))$" | sort -u

# spec outputs must survive
git log --all --format="" --name-only | grep -c "SPEC\.md$"

# source tree must be intact
git log --all --oneline | wc -l
git show HEAD:hyde/user_interface/base_hyde_widgets.py | head -5
```

Check out a branch tip and confirm `hyde/` and `tests/` are complete before
pushing anything.

### 5. Force-push

`git-filter-repo` deliberately removes the `origin` remote to prevent an
accidental push. Push explicitly:

```bash
git push --force --mirror https://github.com/spielman-group/hyde
```

If GitHub rejects writes to `refs/pull/*`, push the branches explicitly instead
of using `--mirror`.

### 6. Deal with GitHub-side residue

A force-push does **not** immediately make the old objects unreachable on
GitHub. Detached commits stay accessible by direct SHA URL until GitHub garbage
collects. Open a GitHub Support request asking them to run garbage collection on
`spielman-group/hyde`, stating that the purpose is removal of copyrighted
third-party material. Do not consider the purge complete until they confirm.

The nuclear alternative — deleting and recreating the repository — guarantees
removal with no Support round-trip, but destroys the 19 closed issues. Since
those issues document the project's work history, prefer the Support route.

### 7. Coordinate afterward

Every existing clone is now poisoned and must be **re-cloned**, not pulled.
Delete old clones outright. A single `git push` from a stale clone restores the
purged blobs.

## Accepted costs

- All commit SHAs from the first affected commit change. Any SHA referenced in
  the 19 closed issues becomes a dead link.
- Existing clones and worktrees must be discarded and re-cloned.
- `specifications/UI_SPEC.md` leaves history along with the directory it lived
  in.
