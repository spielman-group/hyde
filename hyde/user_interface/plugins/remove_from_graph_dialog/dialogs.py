import re

from qtutils.qt import QtWidgets

from hyde.user_interface.plugins.figure_control_dialog.figure_dialog_widget import HydeFigureDialogWidget


class RemoveFromGraphDialog(HydeFigureDialogWidget):
    figure_patch_command_name = "remove_from_graph"

    def __init__(self, figure_context, services=None, parent=None):
        self._visible_trace_rows = ()
        self._filter_error_message = ""
        super().__init__(
            figure_context=figure_context,
            parent=parent,
            services=services,
        )
        self.setWindowTitle("Remove from Graph")
        self.resize(560, 420)
        self.load_ui("remove_from_graph_dialog.ui", module_name=__name__)
        self.ui.trace_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.ui.filter_edit.textChanged.connect(self._on_filter_text_changed)
        self.ui.trace_list.itemSelectionChanged.connect(
            self._on_trace_selection_changed
        )
        self._load_traces()

    def _load_traces(self):
        self._apply_trace_filter()
        self._refresh_from_selection()

    def _on_filter_text_changed(self, _text):
        self._apply_trace_filter()
        self._refresh_from_selection()

    def _on_trace_selection_changed(self):
        self._refresh_from_selection()

    def _apply_trace_filter(self):
        selected_trace_ids = self.selected_supported_trace_ids(self.ui.trace_list)
        current_trace_id = self.current_supported_trace_id(self.ui.trace_list)
        rows, error_message = self._filtered_trace_rows(self.ui.filter_edit.text())
        if error_message:
            self._filter_error_message = error_message
            return self._visible_trace_rows
        self._filter_error_message = ""
        self._visible_trace_rows = rows
        visible_trace_ids = {row["trace_id"] for row in rows}
        self.refresh_supported_trace_list(
            self.ui.trace_list,
            rows=rows,
            selected_trace_ids=tuple(
                trace_id
                for trace_id in selected_trace_ids
                if trace_id in visible_trace_ids
            ),
            current_trace_id=(
                current_trace_id
                if current_trace_id in visible_trace_ids
                else None
            ),
        )
        return tuple(self._visible_trace_rows)

    def _filtered_trace_rows(self, pattern_text):
        trace_rows = self._available_trace_rows()
        pattern = str(pattern_text or "")
        if not pattern:
            return tuple(trace_rows), ""
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return None, f"Invalid regex: {exc}"
        return tuple(row for row in trace_rows if regex.search(row["display_name"])), ""

    def _apply_filter_feedback(self):
        if self._filter_error_message:
            self.set_preview_string(
                self.preview_string(),
                display_text=self._filter_error_message,
            )
        self.refresh_shell()

    def _available_trace_rows(self):
        opening_figure_ir = self.opening_figure_ir
        if opening_figure_ir is None:
            return self.supported_trace_records()
        return opening_figure_ir.supported_trace_records()

    def _refresh_from_selection(self):
        trace_records = self._available_trace_rows()
        if not trace_records:
            self.current_figure_ir = self.opening_figure_ir
            self.set_preview_message("No supported traces available to remove.")
            self._apply_filter_feedback()
            return

        if not self._visible_trace_rows:
            self.current_figure_ir = self.opening_figure_ir
            self.set_preview_message("No traces match the current filter.")
            self._apply_filter_feedback()
            return

        selected_trace_ids = self.selected_supported_trace_ids(self.ui.trace_list)
        self.current_figure_ir = self.opening_figure_ir
        if not selected_trace_ids:
            self.set_preview_message("Select one or more traces to remove.")
            self._apply_filter_feedback()
            return

        self.current_figure_ir = self.current_figure_ir.remove_traces(selected_trace_ids)
        self.refresh_figure_preview()
        self._apply_filter_feedback()
