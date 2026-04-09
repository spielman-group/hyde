from __future__ import annotations

import ast

import numpy as np
from qtutils.qt import QtCore, QtGui, QtWidgets


class CombinedTableModel(QtCore.QAbstractTableModel):
    value_edited = QtCore.Signal(str, int, int, object, bool)

    def __init__(self, table_snapshot, parent=None):
        super().__init__(parent)
        self._apply_snapshot(table_snapshot)

    def _apply_snapshot(self, table_snapshot):
        self.table_snapshot = table_snapshot
        self.columns = [("Point", None, None)]
        self.data_by_name = {}
        self.object_column_counts = {}
        self.max_data_rows = 0
        for name, values in table_snapshot["data"].items():
            matrix = self._normalize(values)
            self.data_by_name[name] = matrix
            self.max_data_rows = max(self.max_data_rows, len(matrix))
            column_count = len(matrix[0]) if matrix else 1
            self.object_column_counts[name] = column_count
            for column in range(column_count):
                label = name if column_count == 1 else f"{name}[{column}]"
                self.columns.append((label, name, column))
        self.row_total = self.max_data_rows + 1

    def replace_snapshot(self, table_snapshot):
        self.beginResetModel()
        self._apply_snapshot(table_snapshot)
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else self.row_total

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal:
            return self.columns[section][0]
        return str(section)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        if index.column() == 0:
            if role == QtCore.Qt.TextAlignmentRole:
                return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            if role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
                return "" if index.row() >= self.max_data_rows else index.row()
            return None
        _label, object_name, subcolumn = self.columns[index.column()]
        matrix = self.data_by_name[object_name]
        if role == QtCore.Qt.TextAlignmentRole:
            return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        if role == QtCore.Qt.BackgroundRole and self._is_append_target(index):
            return QtGui.QBrush(QtGui.QColor("#c8c8c8"))
        if index.row() >= len(matrix) or subcolumn >= len(matrix[index.row()]):
            return "" if role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole) else None
        value = matrix[index.row()][subcolumn]
        if role == QtCore.Qt.DisplayRole:
            return self._display_text(value)
        if role == QtCore.Qt.EditRole:
            return value
        return None

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        if role != QtCore.Qt.EditRole or not index.isValid() or index.column() == 0:
            return False
        _label, object_name, subcolumn = self.columns[index.column()]
        matrix = self.data_by_name[object_name]
        if self._is_append_target(index):
            if isinstance(value, str):
                try:
                    value = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    pass
            self.beginResetModel()
            matrix.append([value])
            self.max_data_rows = max(len(rows) for rows in self.data_by_name.values())
            self.row_total = self.max_data_rows + 1
            self.endResetModel()
            self.value_edited.emit(object_name, index.row(), subcolumn, value, True)
            return True
        if index.row() >= len(matrix) or subcolumn >= len(matrix[index.row()]):
            return False
        if isinstance(value, str):
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                pass
        matrix[index.row()][subcolumn] = value
        self.dataChanged.emit(index, index, [role, QtCore.Qt.DisplayRole])
        self.value_edited.emit(object_name, index.row(), subcolumn, value, False)
        return True

    def flags(self, index):
        if not index.isValid():
            return QtCore.Qt.NoItemFlags
        flags = QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled
        if index.column() != 0 and (self._has_value(index) or self._is_append_target(index)):
            flags |= QtCore.Qt.ItemIsEditable
        return flags

    def full_precision_text(self, index):
        if not index.isValid():
            return ""
        if index.column() == 0:
            return ""
        value = self.data(index, QtCore.Qt.EditRole)
        if value in (None, ""):
            return ""
        if isinstance(value, (float, np.floating)):
            return np.format_float_positional(float(value), precision=15, trim="-")
        return repr(value)

    def _normalize(self, values):
        if not values:
            return []
        if isinstance(values[0], list):
            return [list(row) for row in values]
        return [[value] for value in values]

    def _display_text(self, value):
        if isinstance(value, (float, np.floating)):
            return np.format_float_positional(float(value), precision=8, trim="-")
        return repr(value)

    def _has_value(self, index):
        if index.column() == 0:
            return False
        _label, object_name, subcolumn = self.columns[index.column()]
        matrix = self.data_by_name[object_name]
        return index.row() < len(matrix) and subcolumn < len(matrix[index.row()])

    def _is_append_target(self, index):
        if index.column() == 0:
            return False
        _label, object_name, subcolumn = self.columns[index.column()]
        matrix = self.data_by_name[object_name]
        return (
            self.object_column_counts.get(object_name, 1) == 1
            and subcolumn == 0
            and index.row() == len(matrix)
        )