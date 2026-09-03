"""A terse figure IR for tests that need one but are not about building one.

Roughly sixty tests across five modules want to say "a figure IR titled T with
these traces" and then go on to assert something else entirely -- a dialog's
fields, a comm action, a trace-style edit, a workspace's bookkeeping. They said
it through `figure_ir_from_live_state`, which lived in
`hyde/features/matplotlib_features.py` and took the retired `figure_command`
state as its input. Nothing in production ever called it, so it was a test
fixture shipped inside a production module.

Rehomed here, and composed from the production builder rather than shaped as a
dict of its own. `FigureIR().with_title().with_x_name().with_items()` is the
same code the figure plugin runs when a user creates a figure, so this fixture
cannot drift from the IR production actually produces. A hand-written dict
could, and it would take sixty tests with it -- they would keep passing against
a shape production had stopped emitting.
"""

from hyde.features.matplotlib_ir import FigureIR

_DEFAULT_ITEMS = ("trace_a", "trace_b")


def figure_ir_with_traces(
    title="Figure0",
    *,
    x_name="x",
    items=_DEFAULT_ITEMS,
    figsize=None,
):
    """A validated figure IR: one subplot, one line trace per name in `items`.

    The legend follows the trace count, as it does on the creation path in
    production: on for more than one trace, off otherwise.
    """
    builder = FigureIR().with_title(title).with_x_name(x_name).with_items(items)
    if figsize is not None:
        builder = builder.with_figsize(*figsize)
    return builder.normalized_state()
