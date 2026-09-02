"""What a figure copy can carry, and the payload that carries it.

A clipboard MIME type and a `Copy As` menu label are neither matplotlib strings
nor scientific state, so they are not the feature lowerer's to own. They are the
figure export feature's policy, and this is where it lives: which
representations a figure can be copied as, which matplotlib format renders each,
which MIME type that format becomes, and the `QMimeData` the GUI hands to the
clipboard.
"""

from dataclasses import dataclass

from qtutils.qt import QtCore, QtGui

# Clipboard representation per matplotlib output format. A format absent from
# this mapping has no clipboard representation at all: `raw` and `rgba` are raw
# buffers with no MIME type, and `svgz` is gzipped SVG that no application
# pastes, superseded by `svg`.
# Only the formats Hyde actually publishes to a clipboard. Every other raster
# encoding pastes identically, because the platform republishes the image rather
# than the encoding it was handed.
GRAPHICS_CLIPBOARD_MIME_TYPES = {
    "pdf": "application/pdf",
    "svg": "image/svg+xml",
    "png": "image/png",
    # LaTeX source, carried as text rather than as an image.
    "pgf": "text/plain",
}

_RASTER_MIME_TYPE = GRAPHICS_CLIPBOARD_MIME_TYPES["png"]


@dataclass(frozen=True)
class ClipboardRepresentation:
    """One kind of thing a clipboard can carry a figure as.

    A clipboard distinguishes representations, not file formats: the receiving
    application asks for a picture or a drawing or some text, and every raster
    encoding answers the first question identically. `output_format` is which
    matplotlib format serves the representation, which is Hyde's choice and not
    something a user picks.
    """

    key: str
    display_label: str
    output_formats: tuple
    """Candidate formats in preference order; the platform picks one."""

    is_text: bool = False


GRAPHICS_CLIPBOARD_REPRESENTATIONS = (
    # A vector representation carries both, because which one a platform can
    # publish natively differs and the user picks "vector", not a format.
    ClipboardRepresentation("vector", "Vector", ("pdf", "svg")),
    ClipboardRepresentation("image", "Image", ("png",)),
    ClipboardRepresentation("latex", "LaTeX", ("pgf",), is_text=True),
)


def graphics_clipboard_representations():
    """The representations a figure can be copied as, in menu order."""
    return GRAPHICS_CLIPBOARD_REPRESENTATIONS


def combinable_clipboard_representations():
    """The representations a plain Copy carries together.

    Every representation a picture-or-drawing consumer might want, so the
    receiving application takes the best it understands. Text is left out: it is
    exclusive, because an image alongside LaTeX source means pasting into a word
    processor silently yields a picture instead of the source.
    """
    return tuple(
        representation
        for representation in GRAPHICS_CLIPBOARD_REPRESENTATIONS
        if not representation.is_text
    )


def graphics_clipboard_representation(key):
    """Return the named representation, or None if there is no such thing."""
    normalized_key = str(key or "").strip().lower()
    for representation in GRAPHICS_CLIPBOARD_REPRESENTATIONS:
        if representation.key == normalized_key:
            return representation
    return None


def clipboard_representation_for_format(output_format):
    """Return the representation a format is carried as, or None if it is not.

    A format is how Hyde renders a representation, so this is the way back from
    the rendered bytes to the thing the user asked for and has to be told about.
    """
    normalized_format = str(output_format or "").strip().lower()
    for representation in GRAPHICS_CLIPBOARD_REPRESENTATIONS:
        if normalized_format in representation.output_formats:
            return representation
    return None


def clipboard_mime_type_for_format(output_format):
    """Return the clipboard MIME type for a format, or None if it has none."""
    normalized_format = str(output_format or "").strip().lower()
    return GRAPHICS_CLIPBOARD_MIME_TYPES.get(normalized_format)


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
