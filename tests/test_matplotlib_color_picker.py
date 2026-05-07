import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtutils.qt import QtWidgets

from hyde.user_interface.matplotlib_color_picker import (
    MatplotlibColorDialog,
    MatplotlibColorLineEdit,
    normalize_matplotlib_color_text,
)


class TestMatplotlibColorHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QtWidgets.QApplication([])

    def test_normalize_accepts_names_and_tuple_literals(self):
        self.assertEqual(normalize_matplotlib_color_text("green"), "#008000")
        self.assertEqual(
            normalize_matplotlib_color_text("(0.4, 0.9, 1.0)"),
            "#66e6ff",
        )
        self.assertEqual(
            normalize_matplotlib_color_text("(0.4, 0.9, 1.0, 0.5)"),
            "#66e6ff80",
        )

    def test_line_edit_uses_preview_for_auto_and_reverts_invalid_input(self):
        widget = MatplotlibColorLineEdit(allow_empty=False, allow_auto=True)
        try:
            widget.set_committed_text("auto")
            widget.set_swatch_preview_text("green")
            self.assertEqual(widget.text(), "auto")
            self.assertEqual(widget.swatch_color_text(), "#008000")

            widget.setText("not-a-color")
            widget.editingFinished.emit()
            self.assertEqual(widget.text(), "auto")
            self.assertEqual(widget.swatch_color_text(), "#008000")
        finally:
            widget.close()

    def test_dialog_lists_named_colors_and_accepts_tuple_html_text(self):
        dialog = MatplotlibColorDialog(initial_text="green")
        try:
            html_label = next(
                label
                for label in dialog.findChildren(QtWidgets.QLabel)
                if label.text() == "Matplotlib color:"
            )
            colors_label = next(
                label
                for label in dialog.findChildren(QtWidgets.QLabel)
                if label.text() == "Matplotlib colors"
            )
            html_edit = html_label.buddy()
            named_colors_list = colors_label.buddy()

            self.assertIsInstance(html_edit, QtWidgets.QLineEdit)
            self.assertIsInstance(named_colors_list, QtWidgets.QListWidget)
            self.assertEqual(
                [named_colors_list.item(index).text() for index in range(5)],
                ["black", "red", "blue", "green", "white"],
            )
            html_edit.setText("(0.4, 0.9, 1.0, 0.5)")
            dialog.accept()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)
            self.assertEqual(dialog.selected_color_text(), "#66e6ff80")
        finally:
            dialog.close()
