from qtutils.qt import QtCore, QtGui, QtWidgets

from hyde.features.lmfit_features import (
    LmfitCodec,
    attached_display_label,
    attached_display_trace,
    resolve_attached_display_trace_id,
)
from hyde.user_interface.base import HydeGuiState
from hyde.user_interface.hyde_interactive_widget import supported_trace_records
from hyde.user_interface.plugins.figure_control_dialogs.draft_helpers import (
    FigureControlDraftTracker,
)
from hyde.user_interface.window_macro_store import MacroStoreError


class CurveFitState(HydeGuiState):
    codec = LmfitCodec

    def set_x_name(self, independent_var, x_name):
        path = ("settings", "x_names", str(independent_var))
        if x_name:
            self.apply_action({"type": "set", "path": path, "value": x_name})
        else:
            self.apply_action({"type": "clear", "path": path})

    def set_fit_result_name(self, fit_result_name, *, locked):
        if fit_result_name:
            self.apply_action(
                {
                    "type": "set",
                    "path": ("settings", "fit_result_name"),
                    "value": fit_result_name,
                }
            )
        else:
            self.apply_action({"type": "clear", "path": ("settings", "fit_result_name")})
        self.apply_action(
            {
                "type": "set",
                "path": ("settings", "fit_result_name_locked"),
                "value": bool(locked and fit_result_name),
            }
        )

    def set_coefficient_field(self, parameter_name, field_name, value):
        path = ("settings", "coefficients", str(parameter_name), str(field_name))
        if field_name == "vary":
            self.apply_action(
                {"type": "set", "path": path, "value": bool(value)}
            )
            return
        if str(value or "").strip():
            self.apply_action(
                {"type": "set", "path": path, "value": str(value).strip()}
            )
        else:
            self.apply_action({"type": "clear", "path": path})


class CurveFitDialog(QtWidgets.QDialog):
    def __init__(self, figure_window=None, services=None, parent=None):
        super().__init__(parent)
        self.figure_window = figure_window
        self.services = dict(services or {})
        self.state = CurveFitState()
        self._pending_fit_function_name = None
        self._catalog_service = self.services.get("curve_fit_catalog_service")
        self._catalog_status_text = ""
        self._loading_controls = False
        self._current_model = None
        self._live_error_message = ""
        self._live_result_target_name = None
        self._live_restore_store_name = f"_hyde_lmfit_live_restore_{id(self)}"
        self._live_missing_sentinel_name = f"_hyde_lmfit_missing_{id(self)}"
        self._preview_target_name = f"_hyde_lmfit_preview_{id(self)}"
        self._attached_display_tracker = FigureControlDraftTracker()
        self.setModal(True)
        self.setWindowTitle("Curve Fit")
        self.resize(720, 520)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._build_tab_widget())
        layout.addWidget(self._build_preview_controls())
        layout.addWidget(self._build_status_strip())
        layout.addWidget(self._build_footer())

        self.new_fit_function_button.clicked.connect(self._on_new_fit_function_clicked)
        self.preview_mode_combo.currentTextChanged.connect(self._on_preview_mode_changed)
        self.to_clip_button.clicked.connect(self._copy_command_preview_to_clipboard)
        self.weighting_combo.currentTextChanged.connect(self._on_weighting_changed)
        self.suppress_screen_updates_checkbox.toggled.connect(
            self._on_suppress_screen_updates_toggled
        )
        self.show_fit_checkbox.toggled.connect(self._on_show_fit_toggled)
        self.show_residuals_checkbox.toggled.connect(self._on_show_residuals_toggled)

        if self.figure_window is None:
            self.state.apply_action(
                {
                    "type": "set",
                    "path": ("settings", "from_target"),
                    "value": False,
                }
            )
            self.from_target_checkbox.setChecked(False)
            self.from_target_checkbox.setEnabled(False)
            self.show_fit_checkbox.setEnabled(False)
            self.show_residuals_checkbox.setEnabled(False)
        else:
            self._loading_controls = True
            try:
                self.show_fit_checkbox.setChecked(True)
                self.show_residuals_checkbox.setChecked(False)
            finally:
                self._loading_controls = False
            self.state.apply_action(
                {
                    "type": "set",
                    "path": ("settings", "from_target"),
                    "value": True,
                }
            )
            self._seed_attached_display_tracker()

        if self._catalog_service is not None:
            self._catalog_service.catalog_changed.connect(
                self._on_catalog_changed,
                QtCore.Qt.UniqueConnection,
            )
            self._populate_fit_function_combo()
            self._catalog_service.refresh()
        self._refresh_from_state()

    def _build_tab_widget(self):
        self.tab_widget = QtWidgets.QTabWidget(self)
        self.tab_widget.addTab(
            self._build_function_and_data_tab(),
            "Function and Data",
        )
        self.tab_widget.addTab(self._build_data_options_tab(), "Data Options")
        self.tab_widget.addTab(self._build_coefficients_tab(), "Coefficients")
        self.tab_widget.addTab(self._build_output_options_tab(), "Output Options")
        return self.tab_widget

    def _build_function_and_data_tab(self):
        tab = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(tab)

        self.fit_function_combo = QtWidgets.QComboBox(tab)
        self.fit_function_combo.currentTextChanged.connect(self._on_fit_function_changed)
        layout.addRow("Function", self.fit_function_combo)

        self.new_fit_function_button = QtWidgets.QPushButton(
            "New Fit Function...",
            tab,
        )
        layout.addRow("", self.new_fit_function_button)

        self.y_data_combo = QtWidgets.QComboBox(tab)
        self.y_data_combo.currentTextChanged.connect(self._on_y_data_changed)
        layout.addRow("Y Data", self.y_data_combo)

        self.x_data_container = QtWidgets.QWidget(tab)
        self.x_data_form = QtWidgets.QFormLayout(self.x_data_container)
        self.x_data_form.setContentsMargins(0, 0, 0, 0)
        self.x_data_rows = []
        layout.addRow("X Data", self.x_data_container)

        self.from_target_checkbox = QtWidgets.QCheckBox("From Target", tab)
        self.from_target_checkbox.setChecked(self.figure_window is not None)
        self.from_target_checkbox.toggled.connect(self._on_from_target_toggled)
        layout.addRow("", self.from_target_checkbox)
        return tab

    def _build_data_options_tab(self):
        tab = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(tab)

        self.weighting_combo = QtWidgets.QComboBox(tab)
        layout.addRow("Weighting", self.weighting_combo)

        self.suppress_screen_updates_checkbox = QtWidgets.QCheckBox(
            "Suppress Screen Updates",
            tab,
        )
        layout.addRow("", self.suppress_screen_updates_checkbox)
        return tab

    def _build_coefficients_tab(self):
        tab = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(tab)

        self.coefficients_table = QtWidgets.QTableWidget(0, 6, tab)
        self.coefficients_table.setHorizontalHeaderLabels(
            [
                "Parameter",
                "Initial Value",
                "Vary",
                "Lower",
                "Upper",
                "Expr",
            ]
        )
        self.coefficients_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.coefficients_table)
        return tab

    def _build_output_options_tab(self):
        tab = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(tab)

        self.fit_result_target_combo = QtWidgets.QComboBox(tab)
        self.fit_result_target_combo.setEditable(True)
        self.fit_result_target_combo.editTextChanged.connect(
            self._on_fit_result_target_changed
        )
        layout.addRow("Fit Result", self.fit_result_target_combo)

        self.show_fit_checkbox = QtWidgets.QCheckBox("Show Fit", self)
        self.show_residuals_checkbox = QtWidgets.QCheckBox("Show Residuals", self)
        layout.addRow("", self.show_fit_checkbox)
        layout.addRow("", self.show_residuals_checkbox)
        return tab

    def _build_preview_controls(self):
        container = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(container)

        header_layout = QtWidgets.QHBoxLayout()
        preview_label = QtWidgets.QLabel("Preview", container)
        header_layout.addWidget(preview_label)
        header_layout.addStretch(1)

        self.preview_mode_combo = QtWidgets.QComboBox(container)
        self.preview_mode_combo.addItems(["Commands", "Equation"])
        header_layout.addWidget(self.preview_mode_combo)
        layout.addLayout(header_layout)

        self.preview_text = QtWidgets.QPlainTextEdit(container)
        self.preview_text.setReadOnly(True)
        layout.addWidget(self.preview_text)
        return container

    def _build_status_strip(self):
        self.status_label = QtWidgets.QLabel("", self)
        self.status_label.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.status_label.setMinimumHeight(24)
        return self.status_label

    def _build_footer(self):
        container = QtWidgets.QWidget(self)
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)

        self.do_it_button = QtWidgets.QPushButton("Do It", container)
        self.do_it_button.clicked.connect(self._on_do_it_clicked)
        layout.addWidget(self.do_it_button)

        self.to_clip_button = QtWidgets.QPushButton("To Clip", container)
        layout.addWidget(self.to_clip_button)

        self.cancel_button = QtWidgets.QPushButton("Cancel", container)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)
        return container

    def _namespace_view(self):
        namespace_view_service = self.services.get("namespace_view_service")
        if namespace_view_service is None:
            return {}
        return namespace_view_service.namespace_view()

    def _context(self):
        fit_functions = []
        if self._catalog_service is not None:
            fit_functions = self._catalog_service.fit_functions()
        return {
            "attached": self.figure_window is not None,
            "fit_functions": fit_functions,
            "namespace_view": self._namespace_view(),
            "trace_records": supported_trace_records(self.figure_window),
        }

    def _update_status_label(self, binding_message=""):
        parts = [
            text
            for text in [
                binding_message,
                self._live_error_message,
                self._catalog_status_text,
            ]
            if str(text or "").strip()
        ]
        self.status_label.setText(" | ".join(parts))

    def _status_message_for_rejections(self, rejected_entries):
        details = []
        for entry in rejected_entries:
            name = entry.get("name")
            if not name:
                continue
            reason = str(entry.get("reason") or "").strip()
            details.append(f"{name}: {reason}" if reason else name)
        if not details:
            return ""
        return "Ignored unsupported fit functions: " + "; ".join(details)

    def _populate_fit_function_combo(self):
        catalog_service = self._catalog_service
        if catalog_service is None:
            return
        entries = list(catalog_service.fit_functions())
        rejected_entries = list(catalog_service.rejected_fit_functions())
        current_name = self.fit_function_combo.currentText().strip()
        self.fit_function_combo.blockSignals(True)
        self.fit_function_combo.clear()
        for entry in entries:
            self.fit_function_combo.addItem(entry["name"], dict(entry))
        self.fit_function_combo.blockSignals(False)

        preferred_name = self._pending_fit_function_name or current_name
        if preferred_name:
            index = self.fit_function_combo.findText(preferred_name)
            if index >= 0:
                self.fit_function_combo.setCurrentIndex(index)
        self._catalog_status_text = self._status_message_for_rejections(rejected_entries)

        if self._pending_fit_function_name:
            index = self.fit_function_combo.findText(self._pending_fit_function_name)
            if index >= 0:
                self.fit_function_combo.setCurrentIndex(index)
                self._pending_fit_function_name = None
        self._refresh_from_state()

    def _on_catalog_changed(self):
        self._populate_fit_function_combo()

    def _on_new_fit_function_clicked(self):
        if self._catalog_service is None:
            return
        default_name = self._catalog_service.default_new_fit_function_name()
        function_name, accepted = QtWidgets.QInputDialog.getText(
            self,
            "New Fit Function",
            "Function Name:",
            text=default_name,
        )
        if not accepted:
            return
        try:
            self._pending_fit_function_name = str(function_name).strip()
            self._catalog_service.scaffold_new_fit_function(
                self._pending_fit_function_name
            )
        except MacroStoreError as exc:
            self._pending_fit_function_name = None
            QtWidgets.QMessageBox.warning(
                self,
                "Unable To Create Fit Function",
                str(exc),
            )

    def _clear_x_data_rows(self):
        while self.x_data_form.rowCount():
            self.x_data_form.removeRow(0)
        self.x_data_rows = []

    def _rebuild_x_data_rows(self, model):
        self._clear_x_data_rows()
        for row in model["x_rows"]:
            combo = QtWidgets.QComboBox(self.x_data_container)
            for option in row["options"]:
                combo.addItem(option)
            if row["value"]:
                index = combo.findText(row["value"])
                if index >= 0:
                    combo.setCurrentIndex(index)
            combo.currentTextChanged.connect(
                lambda value, name=row["name"]: self._on_x_data_changed(name, value)
            )
            self.x_data_form.addRow(row["name"], combo)
            self.x_data_rows.append({"name": row["name"], "combo": combo})

    def _rebuild_coefficient_rows(self, model):
        self.coefficients_table.setRowCount(0)
        for row_index, row in enumerate(model["coefficient_rows"]):
            self.coefficients_table.insertRow(row_index)
            name_item = QtWidgets.QTableWidgetItem(row["name"])
            name_item.setFlags(name_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.coefficients_table.setItem(row_index, 0, name_item)

            initial_edit = QtWidgets.QLineEdit(self.coefficients_table)
            initial_edit.setText(row["initial_value"])
            initial_edit.setEnabled(not row["expression_owned"])
            initial_edit.editingFinished.connect(
                lambda name=row["name"], edit=initial_edit: self._on_coefficient_text_changed(
                    name,
                    "initial_value",
                    edit.text(),
                )
            )
            self.coefficients_table.setCellWidget(row_index, 1, initial_edit)

            vary_checkbox = QtWidgets.QCheckBox(self.coefficients_table)
            vary_checkbox.setChecked(bool(row["vary"]))
            vary_checkbox.setEnabled(not row["expression_owned"])
            vary_checkbox.toggled.connect(
                lambda checked, name=row["name"]: self._on_coefficient_vary_changed(
                    name,
                    checked,
                )
            )
            self.coefficients_table.setCellWidget(row_index, 2, vary_checkbox)

            lower_edit = QtWidgets.QLineEdit(self.coefficients_table)
            lower_edit.setText(row["lower_bound"])
            lower_edit.setEnabled(not row["expression_owned"])
            lower_edit.editingFinished.connect(
                lambda name=row["name"], edit=lower_edit: self._on_coefficient_text_changed(
                    name,
                    "lower_bound",
                    edit.text(),
                )
            )
            self.coefficients_table.setCellWidget(row_index, 3, lower_edit)

            upper_edit = QtWidgets.QLineEdit(self.coefficients_table)
            upper_edit.setText(row["upper_bound"])
            upper_edit.setEnabled(not row["expression_owned"])
            upper_edit.editingFinished.connect(
                lambda name=row["name"], edit=upper_edit: self._on_coefficient_text_changed(
                    name,
                    "upper_bound",
                    edit.text(),
                )
            )
            self.coefficients_table.setCellWidget(row_index, 4, upper_edit)

            expr_edit = QtWidgets.QLineEdit(self.coefficients_table)
            expr_edit.setText(row["expr"])
            expr_edit.editingFinished.connect(
                lambda name=row["name"], edit=expr_edit: self._on_coefficient_text_changed(
                    name,
                    "expr",
                    edit.text(),
                )
            )
            self.coefficients_table.setCellWidget(row_index, 5, expr_edit)

    def _refresh_from_state(self):
        model = self.state.codec.present_state(self.state._state, context=self._context())
        self._current_model = dict(model)
        self._loading_controls = True
        try:
            fit_function_name = model["fit_function_name"] or ""
            index = self.fit_function_combo.findText(fit_function_name)
            self.fit_function_combo.setCurrentIndex(index)

            self.y_data_combo.clear()
            for option in model["y_options"]:
                self.y_data_combo.addItem(option)
            y_index = self.y_data_combo.findText(model["y_name"] or "")
            self.y_data_combo.setCurrentIndex(y_index)

            self._rebuild_x_data_rows(model)
            self._rebuild_coefficient_rows(model)

            self.weighting_combo.clear()
            for option in model["weighting_options"]:
                self.weighting_combo.addItem(option)
            weighting_index = self.weighting_combo.findText(model["weighting_name"])
            self.weighting_combo.setCurrentIndex(weighting_index)
            self.suppress_screen_updates_checkbox.setChecked(
                bool(model["suppress_screen_updates"])
            )

            self.fit_result_target_combo.clear()
            for option in model["fit_result_options"]:
                self.fit_result_target_combo.addItem(option)
            self.fit_result_target_combo.setEditText(model["fit_result_name"])

            preview_mode = str(model.get("preview_mode") or "Commands")
            preview_index = self.preview_mode_combo.findText(preview_mode)
            self.preview_mode_combo.setCurrentIndex(preview_index)
            if preview_mode == "Equation":
                self.preview_text.setPlainText(model["equation_preview"])
            else:
                self.preview_text.setPlainText(model["commands_preview"])
            self.do_it_button.setEnabled(
                bool(model["valid"]) and not self._live_error_message
            )
            self._update_status_label(model["status_message"])
        finally:
            self._loading_controls = False

    def _attached_display_figure_state(self):
        subplot_state = self._attached_display_subplot_state()
        if subplot_state is None:
            return None
        fit_trace = self._attached_display_trace_entry(
            subplot_state["traces"],
            "best_fit",
        )
        residual_trace = self._attached_display_trace_entry(
            subplot_state["traces"],
            "residual",
        )
        fit_result_name = None
        if fit_trace is not None:
            fit_result_name = fit_trace["fit_result_name"]
        elif residual_trace is not None:
            fit_result_name = residual_trace["fit_result_name"]
        return {
            "subplot_id": subplot_state["subplot_id"],
            "fit_trace_id": None if fit_trace is None else fit_trace["trace_id"],
            "fit_trace": None if fit_trace is None else fit_trace["trace"],
            "residual_trace_id": (
                None if residual_trace is None else residual_trace["trace_id"]
            ),
            "residual_trace": (
                None if residual_trace is None else residual_trace["trace"]
            ),
            "fit_result_name": fit_result_name,
        }

    def _attached_display_subplot_state(self):
        if self.figure_window is None:
            return None
        snapshot_state = getattr(self.figure_window, "snapshot_state", None)
        figure_ir = {} if snapshot_state is None else (snapshot_state.figure_ir() or {})
        subplots = figure_ir.get("layout", {}).get("subplots", [])
        if not subplots:
            return None
        subplot = dict(subplots[0])
        traces = {
            str(trace.get("id")): dict(trace)
            for trace in subplot.get("traces", [])
            if isinstance(trace, dict)
        }
        return {
            "subplot_id": str(subplot.get("id") or "subplot0"),
            "traces": traces,
        }

    def _attached_display_trace_entry(self, traces, component):
        trace_prefix = "fit_" if component == "best_fit" else "res_"
        for trace in traces.values():
            trace_id = str(trace.get("id") or "").strip()
            if not trace_id.startswith(trace_prefix):
                continue
            y_source = dict(trace.get("y_source") or {})
            if y_source.get("kind") != "attribute_path":
                continue
            root = dict(y_source.get("root") or {})
            if root.get("kind") != "name":
                continue
            path = [str(value) for value in y_source.get("path", [])]
            if path != [str(component)]:
                continue
            fit_result_name = str(root.get("value") or "").strip()
            if not fit_result_name:
                continue
            return {
                "trace_id": trace_id,
                "trace": dict(trace),
                "fit_result_name": fit_result_name,
            }
        return None

    def _seed_attached_display_tracker(self):
        display_state = self._attached_display_figure_state()
        if display_state is None:
            return
        default_show_fit = (
            display_state["fit_trace"] is None
            and display_state["residual_trace"] is None
        )
        opening_state = {
            "subplot_id": display_state["subplot_id"],
            "show_fit": default_show_fit or display_state["fit_trace"] is not None,
            "show_residuals": display_state["residual_trace"] is not None,
            "fit_trace_id": display_state["fit_trace_id"],
            "residual_trace_id": display_state["residual_trace_id"],
            "fit_result_name": display_state["fit_result_name"],
        }
        self._attached_display_tracker.seed(
            "attached_display",
            opening_state,
            revert_state=display_state,
        )
        self._loading_controls = True
        try:
            self.show_fit_checkbox.setChecked(bool(opening_state["show_fit"]))
            self.show_residuals_checkbox.setChecked(bool(opening_state["show_residuals"]))
        finally:
            self._loading_controls = False

    def _current_attached_display_state(self):
        current_state = self._attached_display_tracker.current_states.get(
            "attached_display"
        )
        if current_state is None:
            return None
        show_fit = bool(self.show_fit_checkbox.isChecked())
        show_residuals = bool(self.show_residuals_checkbox.isChecked())
        fit_result_name = current_state.get("fit_result_name")
        if show_fit or show_residuals:
            fit_result_name = str(
                self._current_model.get("fit_result_name")
                if self._current_model is not None
                else fit_result_name
                or ""
            ).strip()
        return {
            "subplot_id": current_state["subplot_id"],
            "show_fit": show_fit,
            "show_residuals": show_residuals,
            "fit_trace_id": current_state.get("fit_trace_id"),
            "residual_trace_id": current_state.get("residual_trace_id"),
            "fit_result_name": fit_result_name or None,
        }

    def _attached_plot_x_name(self):
        if self._current_model is None:
            return None
        x_rows = list(self._current_model.get("x_rows") or [])
        if not x_rows:
            return None
        return x_rows[0].get("value")

    def _attached_display_failure_message(self):
        return "Curve Fit attached display update failed."

    def _apply_attached_display_actions(self, subplot_id, trace_actions):
        rollback_state = self._attached_display_subplot_state()
        applied_trace_ids = []
        for trace_id, trace in trace_actions:
            if self.figure_window.request_figure_action(
                {
                    "type": "set_trace",
                    "subplot_id": subplot_id,
                    "trace_id": trace_id,
                    "trace": trace,
                }
            ):
                applied_trace_ids.append(trace_id)
                continue
            if rollback_state is not None:
                for applied_trace_id in reversed(applied_trace_ids):
                    self.figure_window.request_figure_action(
                        {
                            "type": "set_trace",
                            "subplot_id": subplot_id,
                            "trace_id": applied_trace_id,
                            "trace": rollback_state["traces"].get(applied_trace_id),
                        }
                    )
            return False
        return True

    def _run_hidden_command(
        self,
        command,
        *,
        success_target_name=None,
        display_root_name=None,
    ):
        python_execution_service = self.services.get("python_execution_service")
        if python_execution_service is None:
            return False, "Curve Fit requires python_execution_service."
        if not python_execution_service.execute_hidden(command):
            return False, self._execution_failure_message(python_execution_service)
        if not self._sync_attached_display(force=True, root_name=display_root_name):
            rollback_command = self.state.codec.state_to_restore_target_python(
                success_target_name,
                restore_store_name=self._live_restore_store_name,
                missing_sentinel_name=self._live_missing_sentinel_name,
            )
            if rollback_command:
                python_execution_service.execute_hidden(rollback_command)
            return False, self._attached_display_failure_message()
        if success_target_name is not None:
            self._live_result_target_name = success_target_name
        return True, ""

    def _sync_preview_object(self):
        if self.figure_window is None or self._current_model is None:
            return True
        current_state = self._attached_display_tracker.current_states.get(
            "attached_display"
        )
        if current_state is None:
            return True
        if not (self.show_fit_checkbox.isChecked() or self.show_residuals_checkbox.isChecked()):
            return True
        preview_command = self.state.codec.state_to_preview_python(
            self.state._state,
            context=self._context(),
            preview_target_name=self._preview_target_name,
        )
        if not preview_command:
            return False
        python_execution_service = self.services.get("python_execution_service")
        if python_execution_service is None:
            return False
        return bool(python_execution_service.execute_hidden(preview_command))

    def _sync_attached_display(self, *, force=False, root_name=None):
        current_state = self._attached_display_tracker.current_states.get(
            "attached_display"
        )
        desired_state = self._current_attached_display_state()
        if current_state is None or desired_state is None:
            return True
        if not force and desired_state == current_state:
            return True
        has_plot = bool(desired_state["show_fit"] or desired_state["show_residuals"])
        if force and not has_plot and not (
            current_state["show_fit"] or current_state["show_residuals"]
        ):
            return True
        if has_plot:
            if self._current_model is None or not self._current_model.get("valid"):
                return False
            fit_result_name = str(desired_state.get("fit_result_name") or "").strip()
            if not fit_result_name:
                return False
            resolved_root_name = (
                str(root_name).strip() if root_name is not None else self._preview_target_name
            )
            if resolved_root_name == self._preview_target_name and not self._sync_preview_object():
                return False
            x_name = self._attached_plot_x_name()
            subplot_state = self._attached_display_subplot_state()
            existing_trace_ids = (
                set()
                if subplot_state is None
                else set(subplot_state.get("traces", {}))
            )
            fit_trace_id = None
            residual_trace_id = None
            if desired_state["show_fit"]:
                fit_trace_id = resolve_attached_display_trace_id(
                    fit_result_name,
                    "best_fit",
                    existing_trace_ids - {current_state.get("fit_trace_id")},
                    requested_trace_id=current_state.get("fit_trace_id"),
                )
                existing_trace_ids.add(fit_trace_id)
            fit_trace = (
                attached_display_trace(
                    fit_result_name,
                    x_name,
                    fit_trace_id,
                    "best_fit",
                    attached_display_label(fit_result_name, "best_fit"),
                    {"linestyle": "--"},
                    root_name=resolved_root_name,
                )
                if desired_state["show_fit"]
                else None
            )
            if desired_state["show_residuals"]:
                residual_trace_id = resolve_attached_display_trace_id(
                    fit_result_name,
                    "residual",
                    existing_trace_ids - {current_state.get("residual_trace_id")},
                    requested_trace_id=current_state.get("residual_trace_id"),
                )
                existing_trace_ids.add(residual_trace_id)
            residual_trace = (
                attached_display_trace(
                    fit_result_name,
                    x_name,
                    residual_trace_id,
                    "residual",
                    attached_display_label(fit_result_name, "residual"),
                    {"linestyle": ":"},
                    root_name=resolved_root_name,
                )
                if desired_state["show_residuals"]
                else None
            )
        else:
            fit_trace = None
            residual_trace = None
            fit_trace_id = None
            residual_trace_id = None
        trace_actions = []
        current_fit_trace_id = current_state.get("fit_trace_id")
        current_residual_trace_id = current_state.get("residual_trace_id")
        if current_fit_trace_id and current_fit_trace_id != fit_trace_id:
            trace_actions.append((current_fit_trace_id, None))
        if desired_state["show_fit"] and (
            force
            or desired_state["show_fit"] != current_state["show_fit"]
            or current_fit_trace_id != fit_trace_id
            or desired_state.get("fit_result_name") != current_state.get("fit_result_name")
        ):
            trace_actions.append((fit_trace_id, fit_trace))
        if current_residual_trace_id and current_residual_trace_id != residual_trace_id:
            trace_actions.append((current_residual_trace_id, None))
        if desired_state["show_residuals"] and (
            force
            or desired_state["show_residuals"] != current_state["show_residuals"]
            or current_residual_trace_id != residual_trace_id
            or desired_state.get("fit_result_name") != current_state.get("fit_result_name")
        ):
            trace_actions.append((residual_trace_id, residual_trace))
        if (
            not desired_state["show_fit"]
            and current_state["show_fit"]
            and current_fit_trace_id
            and current_fit_trace_id == fit_trace_id
        ):
            trace_actions.append((current_fit_trace_id, None))
        if (
            not desired_state["show_residuals"]
            and current_state["show_residuals"]
            and current_residual_trace_id
            and current_residual_trace_id == residual_trace_id
        ):
            trace_actions.append((current_residual_trace_id, None))
        if not trace_actions:
            return True
        if not self._apply_attached_display_actions(
            desired_state["subplot_id"],
            trace_actions,
        ):
            return False
        self._attached_display_tracker.replace(
            "attached_display",
            {
                "subplot_id": desired_state["subplot_id"],
                "show_fit": desired_state["show_fit"],
                "show_residuals": desired_state["show_residuals"],
                "fit_trace_id": fit_trace_id if desired_state["show_fit"] else None,
                "residual_trace_id": (
                    residual_trace_id if desired_state["show_residuals"] else None
                ),
                "fit_result_name": (
                    desired_state.get("fit_result_name") if has_plot else None
                ),
            },
        )
        return True

    def _after_relevant_state_change(self):
        self._refresh_from_state()
        if self._current_model is None:
            return
        if self.execution_mode() != "live" or not self._current_model.get("valid"):
            if self._live_error_message:
                self._live_error_message = ""
                self.do_it_button.setEnabled(bool(self._current_model.get("valid")))
                self._update_status_label(
                    self._current_model.get("status_message", "")
                )
            if (
                self.figure_window is not None
                and self._current_model.get("valid")
                and (self.show_fit_checkbox.isChecked() or self.show_residuals_checkbox.isChecked())
            ):
                self._sync_attached_display(force=True)
            return
        self._maybe_run_live_update()

    def _execution_failure_message(self, python_execution_service):
        detail = str(
            getattr(python_execution_service, "last_error_message", "") or ""
        ).strip()
        if detail:
            return f"Curve Fit execution failed: {detail}"
        return "Curve Fit execution failed."

    def _maybe_run_live_update(self):
        if self._current_model is None or self.execution_mode() != "live":
            return
        if not self._current_model.get("valid"):
            return
        live_command = self.state.codec.state_to_live_python(
            self.state._state,
            context=self._context(),
            previous_target_name=self._live_result_target_name,
            restore_store_name=self._live_restore_store_name,
            missing_sentinel_name=self._live_missing_sentinel_name,
        )
        success, message = self._run_hidden_command(
            live_command,
            success_target_name=self._current_model.get("fit_result_name"),
            display_root_name=self._preview_target_name,
        )
        self._live_error_message = "" if success else message
        self.do_it_button.setEnabled(
            bool(self._current_model.get("valid")) and not self._live_error_message
        )
        self._update_status_label(self._current_model.get("status_message", ""))

    def _on_fit_function_changed(self, fit_function_name):
        if self._loading_controls:
            return
        if fit_function_name:
            self.state.apply_action(
                {
                    "type": "set",
                    "path": ("settings", "fit_function_name"),
                    "value": fit_function_name,
                }
            )
        else:
            self.state.apply_action(
                {"type": "clear", "path": ("settings", "fit_function_name")}
            )
        self._after_relevant_state_change()

    def _on_y_data_changed(self, y_name):
        if self._loading_controls:
            return
        if y_name:
            self.state.apply_action(
                {"type": "set", "path": ("settings", "y_name"), "value": y_name}
            )
        else:
            self.state.apply_action({"type": "clear", "path": ("settings", "y_name")})
        self._after_relevant_state_change()

    def _on_x_data_changed(self, independent_var, x_name):
        if self._loading_controls:
            return
        self.state.set_x_name(independent_var, x_name)
        self._after_relevant_state_change()

    def _on_from_target_toggled(self, checked):
        if self._loading_controls:
            return
        self.state.apply_action(
            {
                "type": "set",
                "path": ("settings", "from_target"),
                "value": bool(checked),
            }
        )
        self._after_relevant_state_change()

    def _on_preview_mode_changed(self, preview_mode):
        if self._loading_controls:
            return
        self.state.apply_action(
            {
                "type": "set",
                "path": ("settings", "preview_mode"),
                "value": preview_mode,
            }
        )
        self._refresh_from_state()

    def _on_weighting_changed(self, weighting_name):
        if self._loading_controls:
            return
        weighting_name = str(weighting_name).strip()
        if weighting_name:
            self.state.apply_action(
                {
                    "type": "set",
                    "path": ("settings", "weighting_name"),
                    "value": weighting_name,
                }
            )
        else:
            self.state.apply_action(
                {"type": "clear", "path": ("settings", "weighting_name")}
            )
        self._after_relevant_state_change()

    def _on_suppress_screen_updates_toggled(self, checked):
        if self._loading_controls:
            return
        self.state.apply_action(
            {
                "type": "set",
                "path": ("settings", "suppress_screen_updates"),
                "value": bool(checked),
            }
        )
        self._after_relevant_state_change()

    def _on_show_fit_toggled(self, checked):
        del checked
        if self._loading_controls:
            return
        self._sync_attached_display()

    def _on_show_residuals_toggled(self, checked):
        del checked
        if self._loading_controls:
            return
        self._sync_attached_display()

    def _on_fit_result_target_changed(self, fit_result_name):
        if self._loading_controls:
            return
        self.state.set_fit_result_name(str(fit_result_name).strip(), locked=True)
        self._after_relevant_state_change()

    def _on_coefficient_text_changed(self, parameter_name, field_name, value):
        if self._loading_controls:
            return
        self.state.set_coefficient_field(parameter_name, field_name, value)
        self._after_relevant_state_change()

    def _on_coefficient_vary_changed(self, parameter_name, checked):
        if self._loading_controls:
            return
        self.state.set_coefficient_field(parameter_name, "vary", checked)
        self._after_relevant_state_change()

    def _on_do_it_clicked(self):
        if self._current_model is None or not self._current_model.get("valid"):
            return
        if self.execution_mode() == "suppressed":
            success, message = self._run_hidden_command(
                self.state.codec.state_to_live_python(
                    self.state._state,
                    context=self._context(),
                    restore_store_name=self._live_restore_store_name,
                    missing_sentinel_name=self._live_missing_sentinel_name,
                ),
                success_target_name=self._current_model.get("fit_result_name"),
                display_root_name=self._current_model.get("fit_result_name"),
            )
            if not success:
                self._update_status_label(message)
                return
        elif not self._sync_attached_display(
            force=True,
            root_name=self._current_model.get("fit_result_name"),
        ):
            self._update_status_label(self._attached_display_failure_message())
            return
        python_execution_service = self.services.get("python_execution_service")
        fit_result_name = str(
            self._current_model.get("fit_result_name") if self._current_model else ""
        ).strip()
        if (
            python_execution_service is not None
            and fit_result_name
            and hasattr(python_execution_service, "execute_visible")
        ):
            python_execution_service.execute_visible(
                f"print({fit_result_name}.fit_report())"
            )
        self.accept()

    def execution_mode(self):
        if self._current_model is None:
            return "suppressed"
        return str(self._current_model.get("execution_mode") or "suppressed")

    def _copy_command_preview_to_clipboard(self):
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setText(
            self._current_model.get("commands_preview", ""),
            QtGui.QClipboard.Clipboard,
        )

    def reject(self):
        if self._attached_display_tracker.changed_keys():
            revert_state = self._attached_display_tracker.revert_state("attached_display")
            current_state = self._attached_display_tracker.current_states.get(
                "attached_display",
                {},
            )
            trace_actions = []
            current_fit_trace_id = current_state.get("fit_trace_id")
            revert_fit_trace_id = revert_state.get("fit_trace_id")
            if current_fit_trace_id and current_fit_trace_id != revert_fit_trace_id:
                trace_actions.append((current_fit_trace_id, None))
            if revert_fit_trace_id is not None:
                trace_actions.append((revert_fit_trace_id, revert_state["fit_trace"]))
            current_residual_trace_id = current_state.get("residual_trace_id")
            revert_residual_trace_id = revert_state.get("residual_trace_id")
            if (
                current_residual_trace_id
                and current_residual_trace_id != revert_residual_trace_id
            ):
                trace_actions.append((current_residual_trace_id, None))
            if revert_residual_trace_id is not None:
                trace_actions.append(
                    (
                        revert_residual_trace_id,
                        revert_state["residual_trace"],
                    )
                )
            self._apply_attached_display_actions(
                revert_state["subplot_id"],
                trace_actions,
            )
        super().reject()
