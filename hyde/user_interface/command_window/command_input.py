"""Command input handler for the command window."""

from __future__ import annotations

from qtutils.qt import QtCore, QtGui, QtWidgets


class CommandInputHandler(QtCore.QObject):
    command_submitted = QtCore.Signal(str)
    completion_requested = QtCore.Signal(str, int)

    def __init__(self, input_widget=None, parent=None):
        super().__init__(parent)
        self.input = input_widget if input_widget is not None else QtWidgets.QLineEdit()
        self.history = []
        self.history_index = 0
        self.history_draft = ""
        self._completion_token = ""
        self._completion_cursor = 0
        self.completer = QtWidgets.QCompleter(self)
        self.completer.setCaseSensitivity(QtCore.Qt.CaseSensitive)
        self.completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self.completer.activated.connect(self._insert_completion)
        self.input.setCompleter(self.completer)
        self.input.installEventFilter(self)
        self.input.returnPressed.connect(self._on_return_pressed)
        self.input.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))

    def _on_return_pressed(self):
        self._submit()

    def _submit(self):
        command = self.input.text().strip()
        if not command:
            return
        if not self.history or self.history[-1] != command:
            self.history.append(command)
        self.history_index = len(self.history)
        self.history_draft = ""
        self.input.clear()
        self.command_submitted.emit(command)

    def eventFilter(self, watched, event):
        if watched is self.input and event.type() == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Up:
                self._navigate_history(-1)
                return True
            if event.key() == QtCore.Qt.Key_Down:
                self._navigate_history(1)
                return True
            if event.key() == QtCore.Qt.Key_Tab:
                self.completion_requested.emit(self.input.text(), self.input.cursorPosition())
                return True
        return super().eventFilter(watched, event)

    def _navigate_history(self, delta):
        if not self.history:
            return
        new_index = self.history_index + delta
        if delta < 0:
            if self.history_index == len(self.history):
                self.history_draft = self.input.text()
            if new_index >= 0:
                self.history_index = new_index
                self.input.setText(self.history[self.history_index])
        elif delta > 0:
            if new_index < len(self.history):
                self.history_index = new_index
                self.input.setText(self.history[self.history_index])
            else:
                self.history_index = len(self.history)
                self.input.setText(self.history_draft)

    def _insert_completion(self, completion):
        line = self.input.text()
        start = max(self._completion_cursor - len(self._completion_token), 0)
        self.input.setText(line[:start] + completion + line[self._completion_cursor:])
        self.input.setCursorPosition(start + len(completion))

    def set_history(self, history):
        self.history = list(history)
        self.history_index = len(self.history)
        self.history_draft = ""

    def apply_completion(self, token, cursor_pos, matches):
        self._completion_token = token
        self._completion_cursor = cursor_pos
        model = QtCore.QStringListModel(matches, self.completer)
        self.completer.setModel(model)
        if not matches:
            return
        if len(matches) == 1:
            self._insert_completion(matches[0])
            return
        rect = self.input.cursorRect()
        rect.setWidth(self.completer.popup().sizeHintForColumn(0) + 24)
        self.completer.complete(rect)

    def insert_command(self, command):
        self.input.setText(command)
        self.input.setFocus(QtCore.Qt.OtherFocusReason)