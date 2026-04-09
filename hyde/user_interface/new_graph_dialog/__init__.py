"""New graph dialog UI package."""

from __future__ import annotations

from qtutils.qt import QtCore, QtWidgets

from hyde.user_interface import load_ui


class NewGraphDialog(QtWidgets.QDialog):
    def __init__(self, object_names, selected_names=None, parent=None):
        super().__init__(parent)
        self.ui = load_ui("new_graph_dialog/new_graph_dialog.ui", self)
        self.figure_name = f"figure_{QtCore.QUuid.createUuid().toString(QtCore.QUuid.Id128)[:8]}"
        self.y_list = self.ui.y_list
        self.x_list = self.ui.x_list
        self.title_edit = self.ui.title_edit
        self.style_combo = self.ui.style_combo
        self.do_it_button = self.ui.do_it_button
        self.to_cmd_button = self.ui.to_cmd_button
        self.to_clip_button = self.ui.to_clip_button
        self.help_button = self.ui.help_button
        self.cancel_button = self.ui.cancel_button
        self.more_choices_button = self.ui.more_choices_button
        self.swap_axes_checkbox = self.ui.swap_axes_checkbox
        self.y_axis_combo = self.ui.y_axis_combo
        self.x_axis_combo = self.ui.x_axis_combo
        self.y_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.x_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.style_combo.addItems(["_none_", "Lines", "Markers", "Lines+Markers", "Dashed"])
        self.y_axis_combo.addItems(["left"])
        self.x_axis_combo.addItems(["bottom"])
        for name in object_names:
            self.y_list.addItem(name)
            self.x_list.addItem(name)
        selected_names = selected_names or []
        self._select_items(self.y_list, selected_names[:1])
        if len(selected_names) > 1:
            self._select_items(self.x_list, [selected_names[1]])
        self.cancel_button.clicked.connect(self.reject)
        self.help_button.clicked.connect(self._show_help)
        self.more_choices_button.clicked.connect(self._show_help)

    def command(self):
        y_names = self.selected_y_names()
        if not y_names:
            return ""
        x_name = self.selected_x_name()
        if self.swap_axes_checkbox.isChecked():
            x_name, y_names = y_names[0], ([x_name] if x_name else [])
            if not y_names:
                return ""
        title = self.title_edit.text().strip() or None
        first_y = y_names[0]
        kwargs = [f"{first_y!r}"]
        if x_name is not None:
            kwargs.append(f"x={x_name!r}")
        if title is not None:
            kwargs.append(f"title={title!r}")
        kwargs.append(f"figure_name={self.figure_name!r}")
        kwargs.extend(self._style_kwargs())
        commands = [f"display({', '.join(kwargs)})"]
        for index, name in enumerate(y_names[1:], start=1):
            append_args = [repr(name)]
            if x_name is not None:
                append_args.append(f"x={x_name!r}")
            append_args.extend(self._style_kwargs())
            commands.append(f"append_to_graph({self.figure_name!r}, {', '.join(append_args)})")
        return "\n".join(commands)

    def selected_y_names(self):
        return [item.text() for item in self.y_list.selectedItems()]

    def selected_x_name(self):
        items = self.x_list.selectedItems()
        return items[0].text() if items else None

    def _select_items(self, widget, names):
        lookup = set(names)
        for index in range(widget.count()):
            item = widget.item(index)
            item.setSelected(item.text() in lookup)

    def _show_help(self):
        QtWidgets.QMessageBox.information(
            self,
            "New Graph",
            "Choose one or more Y arrays, optionally choose an X array, then generate or execute the replayable Python command.",
        )

    def _style_kwargs(self):
        style = self.style_combo.currentText()
        if style in {"", "_none_", "Lines"}:
            return []
        if style == "Markers":
            return ["style='None'", "marker='o'", "linewidth=0.0"]
        if style == "Lines+Markers":
            return ["style='-'", "marker='o'"]
        if style == "Dashed":
            return ["style='--'"]
        return []


__all__ = ["NewGraphDialog"]
