from qtutils.qt import QtCore, QtWidgets

from hyde.features.lmfit_features import (
    CALCULATED_X_NAME,
    LmfitCodec,
    attached_display_label,
)
from hyde.user_interface.shared.core import HydeGuiState
from hyde.user_interface.shared.figure import HydeFigureDialogWidget

from .fit_function_scaffolding import CurveFitCatalogError


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


class CurveFitDialog(HydeFigureDialogWidget):
    figure_patch_command_name = "curve_fit_attached_display"

    def __init__(self, figure_context=None, services=None, parent=None):
        self.state = CurveFitState()
        self._loading_controls = False
        self._current_model = None
        self._live_error_message = ""
        super().__init__(
            parent=parent,
            services=dict(services or {}),
            figure_context=figure_context,
        )
        self._pending_fit_function_name = None
        self._catalog_service = self.services.get("curve_fit_catalog_service")
        self._catalog_status_text = ""
        self._live_result_target_name = None
        self._live_restore_store_name = f"_hyde_lmfit_live_restore_{id(self)}"
        self._live_missing_sentinel_name = f"_hyde_lmfit_missing_{id(self)}"
        self._preview_target_name = f"_hyde_lmfit_preview_{id(self)}"
        self.setModal(True)
        self.setWindowTitle("Curve Fit")
        self.resize(720, 520)
        self.load_ui("curve_fit_dialog.ui", module_name=__name__)
        self.fit_function_combo = self.ui.fit_function_combo
        self.new_fit_function_button = self.ui.new_fit_function_button
        self.y_data_combo = self.ui.y_data_combo
        self.x_data_container = self.ui.x_data_container
        self.x_data_form = self.ui.x_data_form
        self.x_data_rows = []
        self.from_target_checkbox = self.ui.from_target_checkbox
        self.weighting_combo = self.ui.weighting_combo
        self.suppress_screen_updates_checkbox = (
            self.ui.suppress_screen_updates_checkbox
        )
        self.coefficients_table = self.ui.coefficients_table
        self.fit_result_target_combo = self.ui.fit_result_target_combo
        self.show_fit_checkbox = self.ui.show_fit_checkbox
        self.show_residuals_checkbox = self.ui.show_residuals_checkbox
        self.preview_mode_combo = self.ui.preview_mode_combo
        self.status_label = self.ui.status_label
        self.coefficients_table.horizontalHeader().setStretchLastSection(True)
        self.fit_function_combo.currentTextChanged.connect(self._on_fit_function_changed)
        self.y_data_combo.currentTextChanged.connect(self._on_y_data_changed)
        self.from_target_checkbox.toggled.connect(self._on_from_target_toggled)
        self.fit_result_target_combo.editTextChanged.connect(
            self._on_fit_result_target_changed
        )
        self.from_target_checkbox.setChecked(self.figure_context is not None)

        self.new_fit_function_button.clicked.connect(self._on_new_fit_function_clicked)
        self.preview_mode_combo.currentTextChanged.connect(self._on_preview_mode_changed)
        self.weighting_combo.currentTextChanged.connect(self._on_weighting_changed)
        self.suppress_screen_updates_checkbox.toggled.connect(
            self._on_suppress_screen_updates_toggled
        )
        self.show_fit_checkbox.toggled.connect(self._on_show_fit_toggled)
        self.show_residuals_checkbox.toggled.connect(self._on_show_residuals_toggled)

        if self.figure_context is None:
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
                self._seed_attached_display_controls()
            finally:
                self._loading_controls = False
            self.state.apply_action(
                {
                    "type": "set",
                    "path": ("settings", "from_target"),
                    "value": True,
                }
            )

        if self._catalog_service is not None:
            self._catalog_service.catalog_changed.connect(
                self._on_catalog_changed,
                QtCore.Qt.UniqueConnection,
            )
            self._populate_fit_function_combo()
            self._catalog_service.refresh()
        self._refresh_from_state()

    def can_do_it(self):
        model = self._current_model or {}
        return bool(model.get("valid")) and not bool(self._live_error_message)

    def can_send_to_cmd_line(self):
        model = self._current_model or {}
        if str(model.get("preview_mode") or "Commands") != "Commands":
            return False
        return self.service("visible_terminal_service") is not None

    def handle_do_it(self):
        if self._current_model is None or not self._current_model.get("valid"):
            return
        success, message = self._run_commit_path(
            success_target_name=self._current_model.get("fit_result_name"),
            display_root_name=self._current_model.get("fit_result_name"),
        )
        if not success:
            self._update_status_label(message)
            return
        self.accept()

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
            "attached": self.figure_context is not None,
            "fit_functions": fit_functions,
            "namespace_view": self._namespace_view(),
            "trace_records": self.supported_trace_records(),
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
        except CurveFitCatalogError as exc:
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
            preview_index = self.preview_mode_combo.findText(
                str(model.get("preview_mode") or "Commands")
            )
            self.preview_mode_combo.setCurrentIndex(preview_index)

            self._update_status_label(model["status_message"])
            self.refresh_shell()
        finally:
            self._loading_controls = False

    def _attached_display_state_from_effective(self, effective_state):
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
            if path == ("best_fit",):
                fit_trace = dict(trace)
                fit_root_name = root.get("value")
                fit_result_name = str(trace.get("kwargs", {}).get("label") or "").strip() or fit_result_name
            elif path == ("residual",):
                residual_trace = dict(trace)
                residual_root_name = root.get("value")
                fit_result_name = (
                    fit_result_name
                    or str(trace.get("kwargs", {}).get("label") or "").replace("_residuals", "").strip()
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

    def _seed_attached_display_controls(self):
        display_state = self._attached_display_state_from_effective(
            self.opening_effective_state()
        )
        if display_state is None:
            return
        default_show_fit = (
            display_state["fit_trace"] is None
            and display_state["residual_trace"] is None
        )
        self.show_fit_checkbox.setChecked(
            bool(default_show_fit or display_state["fit_trace"] is not None)
        )
        self.show_residuals_checkbox.setChecked(
            bool(display_state["residual_trace"] is not None)
        )

    def _current_attached_display_state(self):
        display_state = self._attached_display_state_from_effective(
            self.applied_effective_state()
        )
        if display_state is None:
            return None
        show_fit = bool(self.show_fit_checkbox.isChecked())
        show_residuals = bool(self.show_residuals_checkbox.isChecked())
        fit_result_name = None
        if show_fit or show_residuals:
            fit_result_name = str(
                self._current_model.get("fit_result_name")
                if self._current_model is not None
                else ""
            ).strip()
        return {
            "subplot_id": display_state["subplot_id"],
            "show_fit": show_fit,
            "show_residuals": show_residuals,
            "fit_result_name": fit_result_name or None,
        }

    def _attached_plot_x_name(self):
        if self._current_model is None:
            return None
        x_rows = list(self._current_model.get("x_rows") or [])
        if not x_rows:
            return None
        x_name = x_rows[0].get("value")
        if x_name == CALCULATED_X_NAME:
            return None
        return x_name

    def _sync_attached_display_draft(self, *, root_name):
        figure_session = self.figure_session()
        if figure_session is None:
            return self.applied_effective_state()
        desired_state = self._current_attached_display_state()
        if desired_state is None:
            return self.applied_effective_state()
        has_plot = bool(desired_state["show_fit"] or desired_state["show_residuals"])
        fit_result_name = (
            str(desired_state.get("fit_result_name") or "").strip() if has_plot else None
        )
        resolved_root_name = (
            str(root_name).strip() if root_name is not None else fit_result_name
        )
        current_display = self._attached_display_state_from_effective(
            self.applied_effective_state()
        ) or {}
        owner_root_names = (
            self._preview_target_name,
            current_display.get("fit_result_name"),
            current_display.get("fit_root_name"),
            current_display.get("residual_root_name"),
            resolved_root_name,
        )
        figure_session.set_attribute_path_lines(
            fit_result_name,
            subplot_id=desired_state["subplot_id"],
            root_name=resolved_root_name,
            x_name=self._attached_plot_x_name(),
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
        return figure_session.current_effective_state()

    def _attached_display_command_source(
        self,
        *,
        root_name,
        include_preview_object=False,
    ):
        target_state = self._sync_attached_display_draft(root_name=root_name)
        refresh_trace_ids = ()
        resolved_root_name = (
            str(root_name).strip() if root_name is not None else None
        )
        target_display = self._attached_display_state_from_effective(target_state) or {}
        if resolved_root_name == self._preview_target_name:
            refresh_ids = []
            if target_display.get("show_fit") and target_display.get("fit_trace_id"):
                refresh_ids.append(target_display["fit_trace_id"])
            if (
                target_display.get("show_residuals")
                and target_display.get("residual_trace_id")
            ):
                refresh_ids.append(target_display["residual_trace_id"])
            refresh_trace_ids = tuple(refresh_ids)
        command_parts = []
        if include_preview_object:
            preview_command = self.state.codec.state_to_preview_python(
                self.state._state,
                context=self._context(),
                preview_target_name=self._preview_target_name,
            )
            if not preview_command:
                return "", target_state
            command_parts.append(str(preview_command).strip())
        patch_code = self.figure_patch_source(
            self.applied_effective_state(),
            target_state,
            refresh_trace_ids=refresh_trace_ids,
        )
        if str(patch_code or "").strip():
            command_parts.append(str(patch_code).strip())
        return "\n".join(command_parts), target_state

    def _execute_attached_display_command(self, code, *, mode, target_state):
        return self.apply_figure_patch_command(
            code,
            mode=mode,
            target_state=target_state,
            refresh_preview=False,
        )

    def _backing_command_source(self):
        model = self._current_model or {}
        if not model.get("valid"):
            return str(model.get("commands_preview") or "")
        command_lines = []
        if self.execution_mode() == "suppressed":
            commit_command = self.state.codec.state_to_commit_python(
                self.state._state,
                context=self._context(),
            )
            if str(commit_command or "").strip():
                command_lines.append(str(commit_command))
        if self.figure_context is not None:
            patch_code, _ = self._attached_display_command_source(
                root_name=model.get("fit_result_name"),
            )
            if str(patch_code or "").strip():
                command_lines.append(str(patch_code))
        if command_lines:
            return "\n".join(command_lines)
        return str(model.get("commands_preview") or "")

    def _sync_preview_strings(self):
        model = self._current_model or {}
        preview_mode = str(model.get("preview_mode") or "Commands")
        display_text = self._backing_command_source()
        if preview_mode == "Equation":
            display_text = str(model.get("equation_preview") or "")
        self.set_preview_string(
            self._backing_command_source(),
            display_text=display_text,
        )

    def refresh_shell(self):
        self._sync_preview_strings()
        super().refresh_shell()

    def _run_commit_path(
        self,
        command=None,
        *,
        success_target_name=None,
        display_root_name=None,
    ):
        python_execution_service = self.services.get("python_execution_service")
        if python_execution_service is None:
            return False, "Curve Fit requires python_execution_service."
        target_effective_state = self.applied_effective_state()
        if command is None and self.execution_mode() == "suppressed":
            command = self.state.codec.state_to_commit_python(
                self.state._state,
                context=self._context(),
            )
        needs_rollback_snapshot = (
            bool(str(command or "").strip())
            and self.figure_context is not None
            and success_target_name is not None
            and display_root_name is not None
        )
        if needs_rollback_snapshot:
            snapshot_command = self.state.codec.state_to_store_target_python(
                success_target_name,
                restore_store_name=self._live_restore_store_name,
                missing_sentinel_name=self._live_missing_sentinel_name,
            )
            if snapshot_command and not python_execution_service.execute_hidden(
                snapshot_command
            ):
                return False, self._execution_failure_message(python_execution_service)
        patch_code = ""
        if display_root_name is not None and self.figure_context is not None:
            patch_code, target_effective_state = self._attached_display_command_source(
                root_name=display_root_name
            )
        combined_command = "\n".join(
            part
            for part in (str(command or "").strip(), str(patch_code or "").strip())
            if part
        )
        if patch_code:
            if not self._execute_attached_display_command(
                combined_command,
                mode="do_it",
                target_state=target_effective_state,
            ):
                if needs_rollback_snapshot:
                    rollback_command = self.state.codec.state_to_restore_target_python(
                        success_target_name,
                        restore_store_name=self._live_restore_store_name,
                        missing_sentinel_name=self._live_missing_sentinel_name,
                    )
                    if rollback_command:
                        python_execution_service.execute_hidden(rollback_command)
                return False, self._execution_failure_message(python_execution_service)
        elif str(command or "").strip() and not python_execution_service.execute_hidden(command):
            return False, self._execution_failure_message(python_execution_service)
        if success_target_name is not None:
            self._live_result_target_name = success_target_name
        return True, ""

    def _run_preview_path(self, *, force=False):
        if self.figure_context is None or self._current_model is None:
            return True
        wants_display = bool(
            self.show_fit_checkbox.isChecked() or self.show_residuals_checkbox.isChecked()
        )
        return self._sync_attached_display(
            force=force,
            root_name=self._preview_target_name,
            include_preview_object=wants_display,
        )

    def _has_active_attached_preview(self):
        display_state = self._attached_display_state_from_effective(
            self.applied_effective_state()
        ) or {}
        return bool(
            display_state.get("fit_trace_id") or display_state.get("residual_trace_id")
        )

    def _sync_attached_display(
        self,
        *,
        force=False,
        root_name=None,
        include_preview_object=False,
    ):
        if self.figure_session() is None:
            return True
        current_state = self._attached_display_state_from_effective(
            self.applied_effective_state()
        )
        desired_state = self._current_attached_display_state()
        if current_state is None or desired_state is None:
            return True
        resolved_root_name = (
            str(root_name).strip()
            if root_name is not None
            else str(desired_state.get("fit_result_name") or "").strip() or None
        )
        if (
            not force
            and current_state["show_fit"] == desired_state["show_fit"]
            and current_state["show_residuals"] == desired_state["show_residuals"]
            and current_state.get("fit_result_name") == desired_state.get("fit_result_name")
            and (
                not desired_state["show_fit"]
                or current_state.get("fit_root_name") == resolved_root_name
            )
            and (
                not desired_state["show_residuals"]
                or current_state.get("residual_root_name") == resolved_root_name
            )
        ):
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
        else:
            resolved_root_name = None
        if include_preview_object and has_plot:
            resolved_root_name = self._preview_target_name
        patch_code, target_effective_state = self._attached_display_command_source(
            root_name=resolved_root_name,
            include_preview_object=bool(include_preview_object and has_plot),
        )
        if not str(patch_code or "").strip():
            return not bool(include_preview_object and has_plot)
        return self._execute_attached_display_command(
            patch_code,
            mode="live_update" if self.execution_mode() == "live" else "preview",
            target_state=target_effective_state,
        )

    def _after_relevant_state_change(self):
        self._refresh_from_state()
        if self._current_model is None:
            return
        if self.execution_mode() == "live" and self._current_model.get("valid"):
            self._maybe_run_live_update()
            return
        if self._live_error_message:
            self._live_error_message = ""
            self._update_status_label(self._current_model.get("status_message", ""))
            self.refresh_shell()
        if (
            self.figure_context is not None
            and (self.show_fit_checkbox.isChecked() or self.show_residuals_checkbox.isChecked())
            and (
                self._has_active_attached_preview()
                or self._current_model.get("valid")
            )
        ):
            self._run_preview_path(force=True)

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
        success, message = self._run_commit_path(
            live_command,
            success_target_name=self._current_model.get("fit_result_name"),
        )
        if success:
            success = self._run_preview_path(force=True)
            message = "" if success else "Curve Fit attached display update failed."
        self._live_error_message = "" if success else message
        self._update_status_label(self._current_model.get("status_message", ""))
        self.refresh_shell()

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
        self._run_preview_path(force=True)
        self.refresh_shell()

    def _on_show_residuals_toggled(self, checked):
        del checked
        if self._loading_controls:
            return
        self._run_preview_path(force=True)
        self.refresh_shell()

    def _on_fit_result_target_changed(self, fit_result_name):
        if self._loading_controls:
            return
        self.state.set_fit_result_name(str(fit_result_name).strip(), locked=True)
        self._after_relevant_state_change()

    def _on_preview_mode_changed(self, preview_mode):
        if self._loading_controls:
            return
        self.state.apply_action(
            {
                "type": "set",
                "path": ("settings", "preview_mode"),
                "value": str(preview_mode),
            }
        )
        self._refresh_from_state()

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

    def execution_mode(self):
        if self._current_model is None:
            return "suppressed"
        return str(self._current_model.get("execution_mode") or "suppressed")

    def reject(self):
        python_execution_service = self.services.get("python_execution_service")
        if (
            python_execution_service is not None
            and self._live_result_target_name is not None
        ):
            rollback_command = self.state.codec.state_to_restore_target_python(
                self._live_result_target_name,
                restore_store_name=self._live_restore_store_name,
                missing_sentinel_name=self._live_missing_sentinel_name,
            )
            if rollback_command:
                python_execution_service.execute_hidden(rollback_command)
        self._live_result_target_name = None
        super().reject()
