from qtutils.qt import QtWidgets


class CurveFitDialog(QtWidgets.QDialog):
    def __init__(self, figure_window=None, parent=None):
        super().__init__(parent)
        self.figure_window = figure_window
        self.setModal(True)
        self.setWindowTitle("Curve Fit")
        self.resize(720, 520)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._build_tab_widget())
        layout.addWidget(self._build_preview_controls())
        layout.addWidget(self._build_status_strip())
        layout.addWidget(self._build_footer())

        if self.figure_window is None:
            self.from_target_checkbox.setChecked(False)
            self.from_target_checkbox.setEnabled(False)
            self.show_fit_checkbox.setEnabled(False)
            self.show_residuals_checkbox.setEnabled(False)

    def _build_tab_widget(self):
        self.tab_widget = QtWidgets.QTabWidget(self)
        self.tab_widget.addTab(self._build_function_and_data_tab(), "Function and Data")
        self.tab_widget.addTab(self._build_data_options_tab(), "Data Options")
        self.tab_widget.addTab(self._build_coefficients_tab(), "Coefficients")
        self.tab_widget.addTab(self._build_output_options_tab(), "Output Options")
        return self.tab_widget

    def _build_function_and_data_tab(self):
        tab = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(tab)

        self.fit_function_combo = QtWidgets.QComboBox(tab)
        layout.addRow("Function", self.fit_function_combo)

        self.new_fit_function_button = QtWidgets.QPushButton("New Fit Function...", tab)
        layout.addRow("", self.new_fit_function_button)

        self.y_data_combo = QtWidgets.QComboBox(tab)
        layout.addRow("Y Data", self.y_data_combo)

        self.x_data_combo = QtWidgets.QComboBox(tab)
        layout.addRow("X Data", self.x_data_combo)

        self.from_target_checkbox = QtWidgets.QCheckBox("From Target", tab)
        self.from_target_checkbox.setChecked(self.figure_window is not None)
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
        self.do_it_button.clicked.connect(self.accept)
        layout.addWidget(self.do_it_button)

        self.to_clip_button = QtWidgets.QPushButton("To Clip", container)
        layout.addWidget(self.to_clip_button)

        self.cancel_button = QtWidgets.QPushButton("Cancel", container)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)
        return container
