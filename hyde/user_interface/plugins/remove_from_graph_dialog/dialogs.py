from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface.shared.figure import HydeFigureDialogWidget


class RemoveFromGraphDialog(HydeFigureDialogWidget):
    figure_patch_command_name = "remove_from_graph"

    def __init__(self, figure_context, services=None, parent=None):
        super().__init__(
            figure_context=figure_context,
            parent=parent,
            services=services,
        )
        self.setWindowTitle("Remove from Graph")
        self.resize(560, 420)
        self.load_ui("remove_from_graph_dialog.ui", module_name=__name__)
        self.ui.trace_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.ui.trace_list.itemSelectionChanged.connect(
            self._on_trace_selection_changed
        )
        self._load_traces()

    def _load_traces(self):
        self.refresh_supported_trace_list(self.ui.trace_list)
        blocker = QtCore.QSignalBlocker(self.ui.trace_list)
        try:
            self.ui.trace_list.clearSelection()
            self.ui.trace_list.setCurrentRow(-1)
        finally:
            del blocker
        self._refresh_from_selection()

    def _on_trace_selection_changed(self):
        self._refresh_from_selection()

    def _refresh_from_selection(self):
        trace_records = self.supported_trace_records()
        if not trace_records:
            self.figure_session().reset_current_state()
            self.set_preview_message("No supported traces available to remove.")
            self.refresh_shell()
            return

        selected_trace_ids = self.selected_supported_trace_ids(self.ui.trace_list)
        self.figure_session().reset_current_state()
        if not selected_trace_ids:
            self.set_preview_message("Select one or more traces to remove.")
            self.refresh_shell()
            return

        self.figure_session().remove_traces(selected_trace_ids)
        self.refresh_figure_preview()
