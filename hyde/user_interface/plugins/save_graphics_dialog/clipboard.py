"""Clipboard payload construction for figure copy.

Which MIME type a rendered figure carries is a property of the format, so the
format-to-MIME mapping lives in the feature layer. This module is the Qt-facing
half: it turns rendered bytes into a `QMimeData` the GUI can hand to the
clipboard.
"""

from qtutils.qt import QtCore

from hyde.features.matplotlib_features import clipboard_mime_type_for_format


def clipboard_mime_data(rendered, *, output_format, is_text=False):
    """Return a `QMimeData` carrying `rendered` under its format's MIME type.

    Returns `None` when the format has no clipboard representation, so a caller
    never places an unpasteable payload on the clipboard.
    """
    mime_type = clipboard_mime_type_for_format(output_format)
    if mime_type is None:
        return None

    mime_data = QtCore.QMimeData()
    if is_text:
        # PGF is LaTeX source. It goes on as text because that is what someone
        # copying it intends to paste, and it deliberately carries no image
        # representation: an image companion would mean pasting into a word
        # processor silently yields a picture instead of the source.
        mime_data.setText(rendered.decode("utf-8", errors="replace"))
        return mime_data

    mime_data.setData(mime_type, QtCore.QByteArray(rendered))
    return mime_data
