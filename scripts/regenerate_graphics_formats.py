#!/usr/bin/env python
"""Regenerate the matplotlib graphics-format table Hyde ships.

Hyde does not query matplotlib for its export formats at runtime. That query
imports `matplotlib.pyplot` and resolves an interactive backend as a side
effect, and the GUI process must not do either: it does not own figures, and
once pyplot is imported `configure_gui_matplotlib_backend()` becomes a no-op.

So the table is a generated artifact instead, checked in and reviewable. Run
this when the matplotlib dependency changes; a test fails if the checked-in
table and the installed matplotlib disagree, which is what makes staleness
visible rather than silent.

    python scripts/regenerate_graphics_formats.py

Pass --check to report drift without writing, for use in CI or a pre-commit
hook.
"""

import argparse
import pathlib
import sys

TARGET = (
    pathlib.Path(__file__).resolve().parents[1]
    / "hyde"
    / "features"
    / "matplotlib_graphics_formats.py"
)

TEMPLATE = '''"""Matplotlib export formats available to Hyde.

GENERATED FILE -- do not edit by hand.

Regenerate with `python scripts/regenerate_graphics_formats.py` whenever the
matplotlib dependency changes. Hyde reads this table instead of querying
matplotlib at runtime, because that query imports pyplot and resolves an
interactive backend, which the GUI process must not do.

Generated against matplotlib {version}.
"""

GRAPHICS_EXPORT_FILETYPES = {{
{entries}}}
'''


def current_filetypes():
    from hyde.features.matplotlib_features import runtime_graphics_export_filetypes

    return dict(runtime_graphics_export_filetypes())


def render(filetypes, version):
    entries = "".join(
        f"    {key!r}: {description!r},\n"
        for key, description in sorted(filetypes.items())
    )
    return TEMPLATE.format(version=version, entries=entries)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the checked-in table is stale, without writing it",
    )
    args = parser.parse_args(argv)

    sys.path.insert(0, str(TARGET.parents[2]))
    import matplotlib

    rendered = render(current_filetypes(), matplotlib.__version__)
    existing = TARGET.read_text() if TARGET.exists() else None

    if rendered == existing:
        print(f"up to date against matplotlib {matplotlib.__version__}")
        return 0
    if args.check:
        print(
            f"STALE: {TARGET.name} does not match matplotlib "
            f"{matplotlib.__version__}. Run scripts/regenerate_graphics_formats.py",
            file=sys.stderr,
        )
        return 1

    TARGET.write_text(rendered)
    print(f"wrote {TARGET.relative_to(TARGET.parents[2])} "
          f"for matplotlib {matplotlib.__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
