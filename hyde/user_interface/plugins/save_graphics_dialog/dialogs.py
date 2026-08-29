import os

from qtutils.qt import QtCore, QtWidgets

from hyde.features.matplotlib_ir import FigureIR
from hyde.features.matplotlib_features import (
    graphics_output_transparency_supported,
    graphics_export_formats,
)
from hyde.user_interface.base_hyde_widgets import HydeFileDialog
from hyde.user_interface.plugins.figure_interactive.context import EditableFigureContext


def sanitize_export_basename(name):
    text = str(name or "").strip() or "Figure"
    invalid = {os.sep}
    if os.altsep:
        invalid.add(os.altsep)
    for separator in invalid:
        text = text.replace(separator, "_")
    return text or "Figure"


def require_editable_figure_context(figure_context):
    if not isinstance(figure_context, EditableFigureContext):
        raise TypeError("SaveGraphicsDialog requires an EditableFigureContext.")
    return figure_context


class SaveGraphicsDialog(HydeFileDialog):
    confirm_overwrite = True
    create_suggested_directory = True
    default_dpi = 300
    default_transparent = False
    fallback_figure_size_inches = (6.4, 4.8)

    def __init__(self, figure_context, services=None, parent=None):
        self.figure_context = require_editable_figure_context(figure_context)
        self.export_formats = graphics_export_formats()
        self.selected_format_key = (
            None if not self.export_formats else self.export_formats[0].key
        )
        context_size = self.figure_context.current_size_inches()
        if context_size is None:
            context_size = self.fallback_figure_size_inches
        self._opening_figure_size_inches = tuple(float(value) for value in context_size)
        selected_format = self.selected_export_format()
        self.name_filters = (
            ()
            if selected_format is None
            else (selected_format.name_filter,)
        )
        # HydeFileDialog.__init__ refreshes the preview before this subclass can
        # build its output-options widgets, so the accessors below run against a
        # half-built dialog exactly once. Declare those widgets so that state is
        # visible rather than something each accessor has to probe for.
        self.output_options_ready = False
        self.format_list_widget = None
        self.options_panel = None
        self.dpi_spin_box = None
        self.transparent_checkbox = None
        self.same_size_radio = None
        self.custom_size_radio = None
        self.width_spin_box = None
        self.height_spin_box = None
        super().__init__(parent=parent, services=services)
        self.setWindowTitle("Save Graphics")
        self.load_output_options_ui()
        self.populate_format_list()
        self.apply_selected_format(previous_format=None, update_path=False)
        self.refresh_from_file_selection()

    def figure_name(self):
        if self.figure_context is None:
            return ""
        return str(self.figure_context.figure_name())

    def selected_export_format(self):
        for item in self.export_formats:
            if item.key == self.selected_format_key:
                return item
        return None

    def suggested_path(self):
        project_dir = None
        get_current_project_dir = self.service("get_current_project_dir")
        if callable(get_current_project_dir):
            project_dir = get_current_project_dir()
        selected_format = self.selected_export_format()
        preferred_suffix = ".pdf"
        if selected_format is not None:
            preferred_suffix = selected_format.preferred_suffix
        basename = sanitize_export_basename(self.figure_name()) + preferred_suffix
        if project_dir is None:
            return None
        return os.path.join(project_dir, "exports", basename)

    def build_preview_state(self, selected_path):
        selected_format = self.selected_export_format()
        return FigureIR(figure_name=self.figure_name()).with_save_graphics(
            selected_path,
            output_format="pdf" if selected_format is None else selected_format.key,
            dpi=self.selected_dpi(),
            transparent=self.selected_transparent(),
            size_inches=self.selected_size_override_inches(),
        )

    def load_output_options_ui(self):
        content = self.load_ui("save_graphics_dialog.ui", module_name=__name__, row=1)
        self.format_list_widget = content.format_list_widget
        self.options_panel = content.options_panel
        self.dpi_spin_box = content.dpi_spin_box
        self.transparent_checkbox = content.transparent_checkbox
        self.same_size_radio = content.same_size_radio
        self.custom_size_radio = content.custom_size_radio
        self.width_spin_box = content.width_spin_box
        self.height_spin_box = content.height_spin_box

        self.same_size_radio.toggled.connect(self.on_size_mode_changed)
        self.custom_size_radio.toggled.connect(self.on_size_mode_changed)
        self.format_list_widget.currentItemChanged.connect(
            self.on_format_selection_changed
        )
        self.dpi_spin_box.setValue(self.default_dpi)
        self.dpi_spin_box.valueChanged.connect(
            lambda _value: self.refresh_from_file_selection()
        )
        self.transparent_checkbox.setChecked(self.default_transparent)
        self.transparent_checkbox.toggled.connect(
            lambda _checked: self.refresh_from_file_selection()
        )

        width, height = self.current_figure_size_inches()
        self.width_spin_box.setValue(width)
        self.width_spin_box.valueChanged.connect(self.on_size_value_changed)
        self.height_spin_box.setValue(height)
        self.height_spin_box.valueChanged.connect(self.on_size_value_changed)
        self.output_options_ready = True
        self.apply_same_size_display()

    def populate_format_list(self):
        selected_row = None
        for index, item in enumerate(self.export_formats):
            list_item = QtWidgets.QListWidgetItem(item.display_label)
            list_item.setData(QtCore.Qt.UserRole, item.key)
            self.format_list_widget.addItem(list_item)
            if item.key == self.selected_format_key:
                selected_row = index
        if selected_row is not None:
            self.format_list_widget.setCurrentRow(selected_row)

    def path_for_selected_format(self, current_path, previous_format):
        selected_format = self.selected_export_format()
        if selected_format is None:
            return current_path
        if not current_path:
            return self.suggested_path()
        normalized_path = os.path.abspath(str(current_path))
        stem, suffix = os.path.splitext(normalized_path)
        normalized_suffix = suffix.lower()
        previous_suffix = None
        if previous_format is not None:
            previous_suffix = previous_format.preferred_suffix.lower()
        if not normalized_suffix or normalized_suffix == previous_suffix:
            return stem + selected_format.preferred_suffix
        return normalized_path

    def apply_selected_format(self, previous_format=None, *, update_path=True):
        selected_format = self.selected_export_format()
        if selected_format is None:
            return
        self.name_filters = (selected_format.name_filter,)
        self.file_widget.set_selection_policy(
            allowed_suffixes=(),
            name_filters=(selected_format.name_filter,),
            selected_name_filter=selected_format.name_filter,
        )
        self.sync_transparent_control()
        current_path = self.selected_path()
        resolved_path = (
            self.path_for_selected_format(current_path, previous_format)
            if update_path
            else current_path
        )
        if resolved_path and resolved_path != current_path:
            self.file_widget.set_selected_path(resolved_path)
            return
        self.refresh_from_file_selection()

    def on_format_selection_changed(self, current, previous):
        del previous
        if current is None:
            return
        next_key = current.data(QtCore.Qt.UserRole)
        if next_key == self.selected_format_key:
            return
        previous_format = self.selected_export_format()
        self.selected_format_key = str(next_key or "")
        self.apply_selected_format(previous_format=previous_format)

    def current_figure_size_inches(self):
        return tuple(float(value) for value in self._opening_figure_size_inches)

    def selected_dpi(self):
        if not self.output_options_ready:
            return int(self.default_dpi)
        return int(self.dpi_spin_box.value())

    def selected_transparent(self):
        if not self.output_options_ready:
            return bool(self.default_transparent)
        return bool(
            self.transparent_checkbox.isChecked()
            and self.transparent_checkbox.isEnabled()
        )

    def selected_size_override_inches(self):
        if not self.output_options_ready or not self.custom_size_radio.isChecked():
            return None
        return (
            float(self.width_spin_box.value()),
            float(self.height_spin_box.value()),
        )

    def sync_transparent_control(self):
        if not self.output_options_ready:
            return
        selected_format = self.selected_export_format()
        supported = (
            False
            if selected_format is None
            else graphics_output_transparency_supported(selected_format.key)
        )
        if not supported and self.transparent_checkbox.isChecked():
            blocker = QtCore.QSignalBlocker(self.transparent_checkbox)
            self.transparent_checkbox.setChecked(False)
            del blocker
        self.transparent_checkbox.setEnabled(supported)

    def set_displayed_size_inches(self, width, height):
        for widget, value in (
            (self.width_spin_box, width),
            (self.height_spin_box, height),
        ):
            blocker = QtCore.QSignalBlocker(widget)
            widget.setValue(float(value))
            del blocker

    def apply_same_size_display(self):
        width, height = self.current_figure_size_inches()
        self.set_displayed_size_inches(width, height)
        self.width_spin_box.setEnabled(False)
        self.height_spin_box.setEnabled(False)

    def apply_custom_size_display(self):
        width, height = self.current_figure_size_inches()
        self.set_displayed_size_inches(width, height)
        self.width_spin_box.setEnabled(True)
        self.height_spin_box.setEnabled(True)

    def on_size_mode_changed(self, checked):
        if not checked or not self.output_options_ready:
            return
        if self.same_size_radio.isChecked():
            self.apply_same_size_display()
        else:
            self.apply_custom_size_display()
        self.refresh_from_file_selection()

    def on_size_value_changed(self, _value):
        if self.custom_size_radio.isChecked():
            self.refresh_from_file_selection()
