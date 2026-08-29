import copy

from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface.base_hyde_widgets import HydeDialogWidget

from .figure_dialog_IR import FigureDialogIR


FIGURE_CONTEXT_MEMBERS = (
    "figure_number",
    "figure_name",
    "current_figure_ir",
    "current_size_inches",
    "has_supported_traces",
    "supported_trace_records",
)


def validate_figure_context(figure_context):
    if figure_context is None:
        return None
    missing = [
        member
        for member in FIGURE_CONTEXT_MEMBERS
        if not hasattr(figure_context, member)
    ]
    if missing:
        missing_text = ", ".join(missing)
        raise TypeError(
            "Figure dialogs require an EditableFigureContext-compatible object; "
            f"missing {missing_text}."
        )
    for member in FIGURE_CONTEXT_MEMBERS[1:]:
        if not callable(getattr(figure_context, member)):
            raise TypeError(
                "Figure dialogs require an EditableFigureContext-compatible object; "
                f"{member} must be callable."
            )
    return figure_context


class HydeFigureDialogWidget(HydeDialogWidget):
    figure_patch_command_name = "figure_edit"
    live_update_always_enabled = False
    unsupported_figure_patch_message = (
        "Current changes are not yet representable as a Hyde figure command."
    )

    def __init__(self, *args, figure_context=None, services=None, **kwargs):
        self.figure_context = validate_figure_context(figure_context)
        self._supported_trace_rows = ()
        self._supported_trace_rows_by_id = {}
        super().__init__(*args, services=dict(services or {}), **kwargs)
        self.widget_ir = FigureDialogIR.from_figure_context(self.figure_context)
        self._reload_supported_trace_rows()

    def figure_workflow_ir(self):
        if isinstance(self.widget_ir, FigureDialogIR):
            return self.widget_ir
        return FigureDialogIR()

    @property
    def opening_figure_ir(self):
        return self.figure_workflow_ir().opening_figure_ir

    @property
    def current_figure_ir(self):
        return self.figure_workflow_ir().current_figure_ir

    @current_figure_ir.setter
    def current_figure_ir(self, figure_ir):
        self.widget_ir = self.figure_workflow_ir().with_current_figure_ir(figure_ir)
        self._reload_supported_trace_rows(figure_ir)

    @property
    def applied_figure_ir(self):
        return self.figure_workflow_ir().applied_figure_ir

    @applied_figure_ir.setter
    def applied_figure_ir(self, figure_ir):
        self.widget_ir = self.figure_workflow_ir().with_applied_figure_ir(figure_ir)

    def opening_effective_state(self):
        return self.figure_workflow_ir().opening_effective_state()

    def applied_effective_state(self):
        return self.figure_workflow_ir().applied_effective_state()

    def current_effective_state(self):
        return self.figure_workflow_ir().current_effective_state()

    def figure_patch_state(
        self,
        source_ir,
        target_ir,
        *,
        refresh_trace_ids=(),
        refresh_legend=True,
    ):
        return self.figure_workflow_ir().figure_patch_state(
            source_ir,
            target_ir,
            refresh_trace_ids=refresh_trace_ids,
            refresh_legend=refresh_legend,
        )

    def resolved_figure_patch_preview(
        self,
        source_ir,
        target_ir,
        *,
        refresh_trace_ids=(),
    ):
        patch_ir = self.figure_patch_state(
            source_ir,
            target_ir,
            refresh_trace_ids=refresh_trace_ids,
        )
        code = "" if patch_ir is None else patch_ir.python_source(log=False)
        if str(code or "").strip():
            return str(code), ""
        if source_ir is not None and target_ir is not None and (
            source_ir.normalized_state() != target_ir.normalized_state()
        ):
            return "", str(self.unsupported_figure_patch_message)
        return "", ""

    def refresh_figure_preview(self, error_message=""):
        message = str(error_message or "")
        if message:
            self.set_preview_message(message)
            self.refresh_shell()
            return self.preview_display_text()
        target_ir = self.current_figure_ir
        preview_source_ir = self.preview_source_ir()
        if preview_source_ir is None or target_ir is None:
            self.set_preview_string("")
            self.refresh_shell()
            return self.preview_string()
        try:
            code, preview_message = self.resolved_figure_patch_preview(
                preview_source_ir,
                target_ir,
            )
            if preview_message:
                self.set_preview_message(preview_message)
            else:
                self.set_preview_string(code)
        except Exception as exc:
            self.set_preview_message(str(exc))
        self.refresh_shell()
        return self.preview_string()

    def execute_figure_patch(self, code, *, mode):
        if not str(code or "").strip():
            return True
        return self.execute_hidden_command(code)

    def apply_figure_patch_command(
        self,
        code,
        *,
        mode,
        target_state=None,
        refresh_preview=True,
    ):
        if not str(code or "").strip():
            return True
        if not self.execute_figure_patch(code, mode=mode):
            return False
        if target_state is not None:
            self.applied_figure_ir = target_state
            self._reload_supported_trace_rows(target_state)
        if refresh_preview:
            self.refresh_figure_preview()
        return True

    def apply_figure_patch(self, target_ir, *, mode, refresh_preview=True):
        if self.applied_figure_ir is None or target_ir is None:
            return False
        patch_ir = self.figure_patch_state(
            self.applied_figure_ir,
            target_ir,
        )
        code = "" if patch_ir is None else patch_ir.python_source(log=False)
        return self.apply_figure_patch_command(
            code,
            mode=mode,
            target_state=target_ir,
            refresh_preview=refresh_preview,
        )

    def apply_current_figure_patch(self, *, mode, refresh_preview=True):
        return self.apply_figure_patch(
            self.current_figure_ir,
            mode=mode,
            refresh_preview=refresh_preview,
        )

    def preview_source_ir(self):
        return self.figure_workflow_ir().preview_source_ir(
            live_update_enabled=self.live_update_is_enabled()
        )

    def apply_live_update_figure_patch(self, *, mode):
        target_ir = self.current_figure_ir
        applied_ir = self.applied_figure_ir
        code, preview_message = self.resolved_figure_patch_preview(
            applied_ir,
            target_ir,
        )
        if preview_message:
            self.set_preview_message(preview_message)
            self.refresh_shell()
            return False
        if not str(code or "").strip():
            self.refresh_figure_preview()
            return True
        if not self.apply_figure_patch_command(
            code,
            mode=mode,
            target_state=target_ir,
            refresh_preview=False,
        ):
            return False
        self.refresh_figure_preview()
        return True

    def live_update_is_enabled(self):
        if self.live_update_always_enabled:
            return True
        checkbox = getattr(getattr(self, "ui", None), "live_update_checkbox", None)
        return bool(checkbox is not None and checkbox.isChecked())

    def commit_current_figure_patch(self, *, mode="ok"):
        target_ir = self.current_figure_ir
        if self.dispatch_ok_payload(
            executor=lambda code: self.execute_figure_patch(code, mode=mode),
            accept_on_success=False,
        ):
            if target_ir is not None:
                self.applied_figure_ir = target_ir
                self._reload_supported_trace_rows(target_ir)
            self.accept()
            return True
        return False

    def handle_ok(self):
        if self.live_update_is_enabled():
            self.accept()
            return
        self.commit_current_figure_patch()

    def rollback_figure_patch(self):
        if self.opening_figure_ir is None or self.applied_figure_ir is None:
            return True
        rollback_state = copy.deepcopy(self.opening_figure_ir)
        if not self.apply_figure_patch(
            rollback_state,
            mode="cancel",
            refresh_preview=False,
        ):
            return False
        self.refresh_figure_preview()
        return True

    def reject(self):
        self.rollback_figure_patch()
        super().reject()

    def supported_trace_records(self):
        return copy.deepcopy(self._supported_trace_rows)

    def supported_trace_record(self, trace_id):
        record = self._supported_trace_rows_by_id.get(str(trace_id))
        return None if record is None else copy.deepcopy(record)

    def refresh_supported_trace_list(
        self,
        list_widget,
        *,
        rows=None,
        selected_trace_ids=(),
        current_trace_id=None,
    ):
        rendered_rows = self.supported_trace_records() if rows is None else tuple(
            copy.deepcopy(rows)
        )
        normalized_selected = {str(trace_id) for trace_id in selected_trace_ids}
        normalized_current = (
            None if current_trace_id is None else str(current_trace_id)
        )
        blocker = QtCore.QSignalBlocker(list_widget)
        try:
            list_widget.clear()
            for row in rendered_rows:
                item = QtWidgets.QListWidgetItem(row["display_name"])
                item.setData(QtCore.Qt.UserRole, row["trace_id"])
                list_widget.addItem(item)
                if row["trace_id"] in normalized_selected:
                    item.setSelected(True)
                if row["trace_id"] == normalized_current:
                    list_widget.setCurrentItem(item)
            if normalized_current is None and not normalized_selected:
                list_widget.setCurrentRow(-1)
        finally:
            del blocker
        return rendered_rows

    def current_supported_trace_id(self, list_widget):
        item = list_widget.currentItem()
        if item is None:
            return None
        trace_id = item.data(QtCore.Qt.UserRole)
        return None if trace_id is None else str(trace_id)

    def selected_supported_trace_ids(self, list_widget):
        trace_ids = []
        for item in list_widget.selectedItems():
            trace_id = item.data(QtCore.Qt.UserRole)
            if trace_id is None:
                continue
            trace_ids.append(str(trace_id))
        return tuple(trace_ids)

    def _reload_supported_trace_rows(self, figure_ir=None):
        if self.current_figure_ir is None and figure_ir is None:
            self._supported_trace_rows = ()
            self._supported_trace_rows_by_id = {}
            return self._supported_trace_rows
        rows = []
        rows_by_id = {}
        trace_records = (
            self.current_figure_ir.supported_trace_records()
            if figure_ir is None
            else figure_ir.supported_trace_records()
        )
        for index, record in enumerate(trace_records):
            row = dict(record)
            row["trace_index"] = index
            row["trace_id"] = str(row["trace_id"])
            row["subplot_id"] = str(row["subplot_id"])
            rows.append(row)
            rows_by_id[row["trace_id"]] = dict(row)
        self._supported_trace_rows = tuple(rows)
        self._supported_trace_rows_by_id = rows_by_id
        return self.supported_trace_records()
