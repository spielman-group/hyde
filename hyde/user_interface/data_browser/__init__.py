"""Data browser UI package."""

from hyde.user_interface import load_ui

from qtutils.qt import QtCore, QtWidgets


class DataBrowserWidget(QtWidgets.QWidget):
    display_requested = QtCore.Signal(list)
    edit_requested = QtCore.Signal(list)
    table_requested = QtCore.Signal(list)
    append_graph_requested = QtCore.Signal(list)
    append_table_requested = QtCore.Signal(list)
    delete_requested = QtCore.Signal(list)
    where_used_requested = QtCore.Signal(list)
    fit_requested = QtCore.Signal(list)
    copy_path_requested = QtCore.Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = load_ui("data_browser/data_browser.ui", self)
        self.filter_edit = self.ui.filter_edit
        self.current_folder_edit = self.ui.current_folder_edit
        self.tree = self.ui.tree
        self.summary = self.ui.summary
        self.details_text = self.ui.details_text
        self.waves_checkbox = self.ui.waves_checkbox
        self.variables_checkbox = self.ui.variables_checkbox
        self.strings_checkbox = self.ui.strings_checkbox
        self.info_checkbox = getattr(self.ui, "info_checkbox", None)
        self.plot_checkbox = getattr(self.ui, "plot_checkbox", None)
        self.display_button = self.ui.display_button
        self.edit_button = self.ui.edit_button
        self.append_graph_button = self.ui.append_graph_button
        self.append_table_button = self.ui.append_table_button
        self.delete_button = self.ui.delete_button
        self.where_used_button = getattr(self.ui, "where_used_button", None)
        self.fit_button = getattr(self.ui, "fit_button", None)
        self.entries_by_name = {}

        self.tree.setHeaderLabels(["Name", "Kind", "Type", "Shape", "Preview"])
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.tree.itemSelectionChanged.connect(self._update_summary)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.display_button.clicked.connect(lambda: self._emit(self.display_requested))
        self.edit_button.clicked.connect(lambda: self._emit(self.edit_requested))
        self.append_graph_button.clicked.connect(lambda: self._emit(self.append_graph_requested))
        self.append_table_button.clicked.connect(lambda: self._emit(self.append_table_requested))
        self.delete_button.clicked.connect(lambda: self._emit(self.delete_requested))
        if self.where_used_button is not None:
            self.where_used_button.clicked.connect(lambda: self._emit(self.where_used_requested))
        if self.fit_button is not None:
            self.fit_button.clicked.connect(lambda: self._emit(self.fit_requested))
        self.waves_checkbox.toggled.connect(lambda _checked: self._apply_filter(self.filter_edit.text()))
        self.variables_checkbox.toggled.connect(lambda _checked: self._apply_filter(self.filter_edit.text()))
        self.strings_checkbox.toggled.connect(lambda _checked: self._apply_filter(self.filter_edit.text()))
        if self.info_checkbox is not None:
            self.info_checkbox.toggled.connect(lambda _checked: self._apply_filter(self.filter_edit.text()))
        if self.plot_checkbox is not None:
            self.plot_checkbox.toggled.connect(lambda _checked: self._apply_filter(self.filter_edit.text()))

    def set_objects(self, entries):
        self.entries_by_name = {entry["name"]: entry for entry in entries}
        self.tree.clear()
        for entry in entries:
            item = QtWidgets.QTreeWidgetItem(
                [
                    entry["name"],
                    entry["kind"],
                    entry["type_name"],
                    "x".join(str(value) for value in entry["shape"]),
                    entry["preview"],
                ]
            )
            item.setData(0, QtCore.Qt.UserRole, entry["name"])
            item.setData(0, QtCore.Qt.UserRole + 1, entry)
            self.tree.addTopLevelItem(item)
        self.current_folder_edit.setText("root:")
        self._apply_filter(self.filter_edit.text())
        self._update_summary()

    def selected_names(self):
        return [item.data(0, QtCore.Qt.UserRole) for item in self.tree.selectedItems()]

    def _apply_filter(self, text):
        text = text.strip().lower()
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            entry = item.data(0, QtCore.Qt.UserRole + 1)
            visible = self._matches_display_filter(entry)
            visible = visible and (
                not text or text in item.text(0).lower() or text in item.text(2).lower()
            )
            item.setHidden(not visible)

    def _update_summary(self):
        names = self.selected_names()
        if not names:
            self.summary.setText("No selection")
            self.details_text.clear()
        elif len(names) == 1:
            self.summary.setText(f"Selected: {names[0]}")
            self.details_text.setPlainText(self._entry_details(self.entries_by_name[names[0]]))
        else:
            self.summary.setText(f"Selected {len(names)} objects: {', '.join(names)}")
            self.details_text.setPlainText(
                "\n\n".join(self._entry_details(self.entries_by_name[name]) for name in names[:4])
            )

    def _emit(self, signal):
        signal.emit(self.selected_names())

    def _matches_display_filter(self, entry):
        if entry["kind"] == "numpy":
            return self.waves_checkbox.isChecked()
        if entry["type_name"] == "str":
            return self.strings_checkbox.isChecked()
        if entry["kind"] == "plot":
            return self.plot_checkbox is None or self.plot_checkbox.isChecked()
        if entry["kind"] == "info":
            return self.info_checkbox is None or self.info_checkbox.isChecked()
        return self.variables_checkbox.isChecked()

    def _entry_details(self, entry):
        lines = [
            f"Name: {entry['name']}",
            f"Full Path: root:{entry['name']}",
            f"Kind: {entry['kind']}",
            f"Type: {entry['type_name']}",
        ]
        if entry["shape"]:
            lines.append(f"Shape: {tuple(entry['shape'])}")
        if entry.get("dtype"):
            lines.append(f"DType: {entry['dtype']}")
        lines.append(f"Preview: {entry['preview']}")
        return "\n".join(lines)

    def _show_context_menu(self, position):
        menu = QtWidgets.QMenu(self)
        names = self.selected_names()
        has_selection = bool(names)
        actions = [
            ("Display", lambda: self._emit(self.display_requested)),
            ("Edit", lambda: self._emit(self.edit_requested)),
            ("Append to Graph", lambda: self._emit(self.append_graph_requested)),
            ("Append to Table", lambda: self._emit(self.append_table_requested)),
            ("Copy Full Path", lambda: self._emit(self.copy_path_requested)),
            ("Delete Object", lambda: self._emit(self.delete_requested)),
            ("Show Where Object Is Used...", lambda: self._emit(self.where_used_requested)),
        ]
        for label, callback in actions:
            action = menu.addAction(label)
            action.setEnabled(has_selection)
            action.triggered.connect(callback)
        menu.exec(self.tree.viewport().mapToGlobal(position))


__all__ = ["DataBrowserWidget"]
