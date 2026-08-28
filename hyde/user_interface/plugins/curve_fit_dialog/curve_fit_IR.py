import copy
from dataclasses import replace as dataclass_replace

from hyde.features.lmfit_features import CALCULATED_X_NAME, attached_display_label
from hyde.features.lmfit_ir import LmfitIR
from hyde.features.matplotlib_figure_records import trace_label
from hyde.user_interface.plugins.figure_control_dialog.figure_dialog_IR import FigureDialogIR


class CurveFitIR(LmfitIR):
    def __init__(self, *, figure_dialog_ir=None, state=None):
        super().__init__(state=state)
        self.figure_dialog_ir = (
            FigureDialogIR()
            if figure_dialog_ir is None
            else copy.deepcopy(figure_dialog_ir)
        )
        self.show_fit = False
        self.show_residuals = False

    @classmethod
    def from_figure_context(cls, figure_context):
        return cls(figure_dialog_ir=FigureDialogIR.from_figure_context(figure_context))

    def debug_state(self):
        state = super().debug_state()
        state.update(
            {
                "show_fit": bool(self.show_fit),
                "show_residuals": bool(self.show_residuals),
                "figure_dialog_ir": self.figure_dialog_ir.debug_state(),
            }
        )
        return state

    def set_attached_display(self, *, show_fit=None, show_residuals=None):
        if show_fit is not None:
            self.show_fit = bool(show_fit)
        if show_residuals is not None:
            self.show_residuals = bool(show_residuals)
        return self

    @property
    def opening_figure_ir(self):
        return self.figure_dialog_ir.opening_figure_ir

    @property
    def current_figure_ir(self):
        return self.figure_dialog_ir.current_figure_ir

    def set_current_figure_ir(self, figure_ir):
        self.figure_dialog_ir = self.figure_dialog_ir.with_current_figure_ir(figure_ir)
        return self

    @property
    def applied_figure_ir(self):
        return self.figure_dialog_ir.applied_figure_ir

    def set_applied_figure_ir(self, figure_ir):
        self.figure_dialog_ir = self.figure_dialog_ir.with_applied_figure_ir(figure_ir)
        return self

    def opening_effective_state(self):
        state = self.figure_dialog_ir.opening_effective_state()
        return None if state is None else copy.deepcopy(state)

    def applied_effective_state(self):
        state = self.figure_dialog_ir.applied_effective_state()
        return None if state is None else copy.deepcopy(state)

    def current_effective_state(self):
        state = self.figure_dialog_ir.current_effective_state()
        return None if state is None else copy.deepcopy(state)

    def supported_trace_records(self):
        return self.figure_dialog_ir.supported_trace_records()

    def figure_patch_state(
        self,
        source_ir,
        target_ir,
        *,
        refresh_trace_ids=(),
        refresh_legend=True,
    ):
        return self.figure_dialog_ir.figure_patch_state(
            source_ir,
            target_ir,
            refresh_trace_ids=refresh_trace_ids,
            refresh_legend=refresh_legend,
        )

    def attached_display_state_from_effective(self, effective_state):
        if effective_state is None:
            return None
        layout = dict(effective_state.get("layout", {}) or {})
        subplots = list(layout.get("subplots", []) or [])
        if not subplots:
            return None
        subplot = dict(subplots[0] or {})
        subplot_id = str(subplot.get("id") or "subplot0")
        fit_trace = None
        residual_trace = None
        fit_root_name = None
        residual_root_name = None
        fit_result_name = None
        for trace in list(subplot.get("traces", []) or []):
            y_source = dict(trace.get("y_source") or {})
            if y_source.get("kind") != "attribute_path":
                continue
            root = dict(y_source.get("root") or {})
            path = tuple(y_source.get("path") or ())
            label = trace_label(trace)
            if path == ("best_fit",):
                fit_trace = dict(trace)
                fit_root_name = root.get("value")
                fit_result_name = label or fit_result_name
            elif path == ("residual",):
                residual_trace = dict(trace)
                residual_root_name = root.get("value")
                fit_result_name = (
                    fit_result_name
                    or (
                        None
                        if label is None
                        else label.replace("_residuals", "").strip() or None
                    )
                )
        return {
            "subplot_id": subplot_id,
            "show_fit": fit_trace is not None,
            "show_residuals": residual_trace is not None,
            "fit_trace_id": None if fit_trace is None else fit_trace.get("id"),
            "fit_trace": fit_trace,
            "fit_root_name": fit_root_name,
            "residual_trace_id": None if residual_trace is None else residual_trace.get("id"),
            "residual_trace": residual_trace,
            "residual_root_name": residual_root_name,
            "fit_result_name": fit_result_name,
        }

    def current_attached_display_state(self):
        display_state = self.attached_display_state_from_effective(
            self.applied_effective_state()
        )
        if display_state is None:
            return None
        fit_result_name = None
        if self.show_fit or self.show_residuals:
            fit_result_name = str(
                self.present_state().get("fit_result_name") or ""
            ).strip()
        return {
            "subplot_id": display_state["subplot_id"],
            "show_fit": bool(self.show_fit),
            "show_residuals": bool(self.show_residuals),
            "fit_result_name": fit_result_name or None,
        }

    def attached_plot_x_name(self):
        x_rows = list(self.present_state().get("x_rows") or [])
        if not x_rows:
            return None
        x_name = x_rows[0].get("value")
        if x_name == CALCULATED_X_NAME:
            return None
        return x_name

    def sync_attached_display_draft(self, *, root_name):
        target_ir = self.applied_figure_ir or self.current_figure_ir
        if target_ir is None:
            return self.applied_figure_ir
        desired_state = self.current_attached_display_state()
        if desired_state is None:
            return self.applied_figure_ir
        has_plot = bool(desired_state["show_fit"] or desired_state["show_residuals"])
        fit_result_name = (
            str(desired_state.get("fit_result_name") or "").strip() if has_plot else None
        )
        resolved_root_name = (
            str(root_name).strip() if root_name is not None else fit_result_name
        )
        current_display = self.attached_display_state_from_effective(
            self.applied_effective_state()
        ) or {}
        owner_root_names = (
            self.normalized_state()["settings"].get("preview_target_name"),
            current_display.get("fit_result_name"),
            current_display.get("fit_root_name"),
            current_display.get("residual_root_name"),
            resolved_root_name,
        )
        draft_ir = target_ir.set_attribute_path_lines(
            fit_result_name,
            subplot_id=desired_state["subplot_id"],
            root_name=resolved_root_name,
            x_name=self.attached_plot_x_name(),
            owner_root_names=owner_root_names,
            components=(
                {
                    "component": "best_fit",
                    "visible": desired_state["show_fit"],
                    "label": (
                        None
                        if fit_result_name is None
                        else attached_display_label(fit_result_name, "best_fit")
                    ),
                    "style": {"linestyle": "--"},
                },
                {
                    "component": "residual",
                    "visible": desired_state["show_residuals"],
                    "id_suffix": "_residuals",
                    "label": (
                        None
                        if fit_result_name is None
                        else attached_display_label(fit_result_name, "residual")
                    ),
                    "style": {"linestyle": ":"},
                },
            ),
        )
        return dataclass_replace(draft_ir, figure_state=draft_ir.effective_state())

    def attached_display_command_source(self, *, root_name):
        target_state = self.sync_attached_display_draft(root_name=root_name)
        resolved_root_name = (
            str(root_name).strip() if root_name is not None else None
        )
        refresh_trace_ids = ()
        preview_target_name = self.normalized_state()["settings"].get("preview_target_name")
        target_display = self.attached_display_state_from_effective(
            None if target_state is None else target_state.effective_state()
        ) or {}
        if resolved_root_name == preview_target_name:
            refresh_ids = []
            if target_display.get("show_fit") and target_display.get("fit_trace_id"):
                refresh_ids.append(target_display["fit_trace_id"])
            if (
                target_display.get("show_residuals")
                and target_display.get("residual_trace_id")
            ):
                refresh_ids.append(target_display["residual_trace_id"])
            refresh_trace_ids = tuple(refresh_ids)
        patch_state = self.figure_patch_state(
            self.applied_figure_ir,
            target_state,
            refresh_trace_ids=refresh_trace_ids,
        )
        patch_code = "" if patch_state is None else patch_state.python_source(log=False)
        return patch_code, target_state
