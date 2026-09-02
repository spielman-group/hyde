"""Clipboard payload construction for figure copy.

Which MIME type a rendered figure carries is a property of the format, so the
format-to-MIME mapping lives in the feature layer. This module is the Qt-facing
half: it turns rendered representations into a `QMimeData` the GUI can hand to
the clipboard, and says which representations reached it.
"""

from dataclasses import dataclass

from qtutils.qt import QtCore, QtGui

from hyde.features.matplotlib_features import (
    clipboard_mime_type_for_format,
    clipboard_representation_for_format,
)

_RASTER_MIME_TYPE = "image/png"


@dataclass(frozen=True)
class ClipboardPayload:
    """A `QMimeData` and the representations that are actually on it.

    A copy is offered more than the clipboard ends up carrying: text is
    exclusive, and bytes that will not decode into a picture are left off
    rather than placed as something nothing can paste. The two travel together
    because a copy has to tell the user what it put on the clipboard, and the
    only honest source for that is the payload that was built.
    """

    mime_data: QtCore.QMimeData
    representations: tuple
    """The `ClipboardRepresentation`s placed, in the order they were offered."""

    def describe(self):
        """Name what is on the clipboard, the way the Copy As menu names it."""
        return ", ".join(
            representation.display_label for representation in self.representations
        )


def clipboard_mime_data(representations):
    """Return a `ClipboardPayload` for the rendered representations.

    `representations` is a sequence of `(output_format, rendered_bytes)` in the
    order the receiving application should prefer them. A clipboard holds
    several representations of one content, so a copy can offer a drawing and a
    picture together and let the application pick.

    Returns `None` when nothing offered reaches the clipboard, so a caller
    never places an unpasteable payload -- and otherwise reports what it placed
    rather than what it was asked to place, which are not always the same.
    """
    offered = []
    for output_format, rendered in representations:
        if not rendered:
            continue
        mime_type = clipboard_mime_type_for_format(output_format)
        representation = clipboard_representation_for_format(output_format)
        if mime_type is None or representation is None:
            continue
        offered.append((representation, mime_type, rendered))
    if not offered:
        return None

    mime_data = QtCore.QMimeData()

    text = next(
        (
            (representation, rendered)
            for representation, _mime_type, rendered in offered
            if representation.is_text
        ),
        None,
    )
    if text is not None:
        # LaTeX source is what someone copying it intends to paste, and text is
        # exclusive: an image alongside it would mean pasting into a word
        # processor silently yields a picture instead of the source. So this is
        # the whole payload, and the only representation on it.
        representation, rendered = text
        mime_data.setText(rendered.decode("utf-8", errors="replace"))
        return ClipboardPayload(mime_data, (representation,))

    placed = []
    for representation, mime_type, rendered in offered:
        if mime_type == _RASTER_MIME_TYPE:
            # The MIME types here reach other Qt applications. Everything else
            # on this platform reads the native pasteboard, where Qt publishes
            # an unrecognised MIME type under a private flavour nothing can
            # paste -- so an image set only as bytes puts nothing usable on the
            # clipboard. An image set as an image is republished as the
            # platform's own image flavours, which is what makes a paste work
            # anywhere. Bytes that will not decode can be neither, so they are
            # left off entirely instead of placed as a picture that is not one.
            image = QtGui.QImage.fromData(QtCore.QByteArray(rendered), "PNG")
            if image.isNull():
                continue
            mime_data.setData(mime_type, QtCore.QByteArray(rendered))
            mime_data.setImageData(image)
        else:
            mime_data.setData(mime_type, QtCore.QByteArray(rendered))
        if representation not in placed:
            # Vector offers two formats and a platform may publish both; the
            # user copied one thing either way.
            placed.append(representation)
    if not placed:
        return None
    return ClipboardPayload(mime_data, tuple(placed))
