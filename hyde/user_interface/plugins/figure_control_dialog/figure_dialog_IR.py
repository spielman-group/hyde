import copy
from dataclasses import dataclass, replace as dataclass_replace

from hyde.features.matplotlib_ir import FigureIR
from hyde.user_interface.shared.core import HydeIR


def require_figure_ir(value, *, name):
    if value is None or isinstance(value, FigureIR):
        return value
    raise TypeError(f"{name} must be a FigureIR or None.")


@dataclass(frozen=True)
class FigureDialogIR(HydeIR):
    opening_figure_ir: FigureIR | None = None
    current_figure_ir: FigureIR | None = None
    applied_figure_ir: FigureIR | None = None

    def __post_init__(self):
        require_figure_ir(self.opening_figure_ir, name="opening_figure_ir")
        require_figure_ir(self.current_figure_ir, name="current_figure_ir")
        require_figure_ir(self.applied_figure_ir, name="applied_figure_ir")

    @classmethod
    def from_figure_context(cls, figure_context):
        if figure_context is None:
            return cls()
        opening_ir = require_figure_ir(
            figure_context.current_figure_ir(),
            name="figure_context.current_figure_ir()",
        )
        if opening_ir is None:
            return cls()
        return cls(
            opening_figure_ir=copy.deepcopy(opening_ir),
            current_figure_ir=copy.deepcopy(opening_ir),
            applied_figure_ir=copy.deepcopy(opening_ir),
        )

    def debug_state(self):
        return {
            "opening_figure_ir": (
                None
                if self.opening_figure_ir is None
                else self.opening_figure_ir.debug_state()
            ),
            "current_figure_ir": (
                None
                if self.current_figure_ir is None
                else self.current_figure_ir.debug_state()
            ),
            "applied_figure_ir": (
                None
                if self.applied_figure_ir is None
                else self.applied_figure_ir.debug_state()
            ),
        }

    def with_current_figure_ir(self, figure_ir):
        require_figure_ir(figure_ir, name="figure_ir")
        return dataclass_replace(
            self,
            current_figure_ir=None if figure_ir is None else copy.deepcopy(figure_ir),
        )

    def with_applied_figure_ir(self, figure_ir):
        require_figure_ir(figure_ir, name="figure_ir")
        return dataclass_replace(
            self,
            applied_figure_ir=None if figure_ir is None else copy.deepcopy(figure_ir),
        )

    def opening_effective_state(self):
        if self.opening_figure_ir is None:
            return None
        return self.opening_figure_ir.effective_state()

    def applied_effective_state(self):
        if self.applied_figure_ir is None:
            return None
        return self.applied_figure_ir.effective_state()

    def current_effective_state(self):
        if self.current_figure_ir is None:
            return None
        return self.current_figure_ir.effective_state()

    def supported_trace_records(self):
        if self.current_figure_ir is None:
            return ()
        return self.current_figure_ir.supported_trace_records()

    def preview_source_ir(self, *, live_update_enabled):
        if live_update_enabled:
            return self.opening_figure_ir
        return self.applied_figure_ir

    def resolved_figure_name(self):
        for figure_ir in (
            self.current_figure_ir,
            self.opening_figure_ir,
            self.applied_figure_ir,
        ):
            if figure_ir is not None:
                return str(figure_ir.default_macro_name())
        return None

    def figure_patch_state(
        self,
        source_ir,
        target_ir,
        *,
        refresh_trace_ids=(),
        refresh_legend=True,
    ):
        require_figure_ir(source_ir, name="source_ir")
        require_figure_ir(target_ir, name="target_ir")
        figure_name = self.resolved_figure_name()
        if source_ir is None or target_ir is None or figure_name is None:
            return None
        return source_ir.current_diff(target_ir).as_patch(
            figure_name,
            refresh_trace_ids=refresh_trace_ids,
            refresh_legend=refresh_legend,
        )

    def preview_patch_state(self, *, live_update_enabled, refresh_trace_ids=()):
        return self.figure_patch_state(
            self.preview_source_ir(live_update_enabled=live_update_enabled),
            self.current_figure_ir,
            refresh_trace_ids=refresh_trace_ids,
        )

    def _python_source(self):
        patch_ir = self.preview_patch_state(live_update_enabled=False)
        return "" if patch_ir is None else patch_ir.python_source(log=False)
