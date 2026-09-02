"""Clipboard payload construction for figure copy.

Which MIME type a rendered figure carries is a property of the format, so the
format-to-MIME mapping lives in the feature layer. This module is the Qt-facing
half: it turns rendered representations into a `QMimeData` the GUI can hand to
the clipboard.
"""

from qtutils.qt import QtCore, QtGui

from hyde.features.matplotlib_features import clipboard_mime_type_for_format

_TEXT_MIME_TYPE = "text/plain"


def clipboard_mime_data(representations):
    """Return a `QMimeData` carrying each rendered representation.

    `representations` is a sequence of `(output_format, rendered_bytes)` in the
    order the receiving application should prefer them. A clipboard holds
    several representations of one content, so a copy can offer a drawing and a
    picture together and let the application pick.

    Returns `None` when nothing in `representations` has a clipboard
    representation, so a caller never places an unpasteable payload.
    """
    typed = [
        (clipboard_mime_type_for_format(output_format), rendered)
        for output_format, rendered in representations
        if rendered
    ]
    typed = [(mime_type, rendered) for mime_type, rendered in typed if mime_type]
    if not typed:
        return None

    mime_data = QtCore.QMimeData()

    text = next(
        (rendered for mime_type, rendered in typed if mime_type == _TEXT_MIME_TYPE),
        None,
    )
    if text is not None:
        # LaTeX source is what someone copying it intends to paste, and text is
        # exclusive: an image alongside it would mean pasting into a word
        # processor silently yields a picture instead of the source.
        mime_data.setText(text.decode("utf-8", errors="replace"))
        return mime_data

    for mime_type, rendered in typed:
        mime_data.setData(mime_type, QtCore.QByteArray(rendered))

    raster = next(
        (rendered for mime_type, rendered in typed if mime_type == "image/png"),
        None,
    )
    if raster is not None:
        # The MIME types above reach other Qt applications. Everything else on
        # this platform reads the native pasteboard, where Qt publishes an
        # unrecognised MIME type under a private flavour nothing can paste --
        # so an image set only as bytes puts nothing usable on the clipboard.
        # An image set as an image is republished as the platform's own image
        # flavours, which is what makes a paste work anywhere.
        image = QtGui.QImage.fromData(QtCore.QByteArray(raster), "PNG")
        if not image.isNull():
            mime_data.setImageData(image)
    return mime_data
