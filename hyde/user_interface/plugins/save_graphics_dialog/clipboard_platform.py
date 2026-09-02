"""Which clipboard formats this platform can publish, and how.

A clipboard carries one representation of each kind, and which format a platform
republishes to applications outside Qt differs: macOS reads PDF, and a Linux
selection is MIME-typed at the protocol level so it may take SVG directly. Hyde
therefore renders the one format the running platform can use rather than every
format it knows of.

This is the single place platform knowledge lives. A platform Hyde has not been
verified on is absent rather than guessed at, and falls back to the first format
a representation offers.
"""

import logging
import sys

from qtutils.qt import QtCore, QtGui

LOGGER = logging.getLogger("hyde")

# Verified: a PDF put on the macOS pasteboard as `com.adobe.pdf` pastes into
# applications outside Qt. Linux is deliberately absent -- see
# issues/CLIPBOARD_REPRESENTATIONS.md, where establishing what a Linux selection
# already publishes is a deferred slice. Until that runs it takes the first
# candidate rather than a guess.
_PREFERRED_FORMATS_BY_PLATFORM = {
    "darwin": ("pdf",),
}

# Hyde's vector MIME types against the identifiers this platform knows them by.
_UTI_FOR_MIME_TYPE = {
    "application/pdf": "com.adobe.pdf",
    "image/svg+xml": "public.svg-image",
}

# Qt registers a mime converter when it is constructed and unregisters it when
# it is destroyed, so the instances are owned here for the life of the process.
# Dropping them unregisters silently, and the symptom is that vector paste
# works sometimes.
_REGISTERED_CONVERTERS = []


def preferred_clipboard_format(candidate_formats):
    """The one format this platform publishes for a representation.

    `candidate_formats` is the representation's candidates in preference order,
    so an unverified platform takes the first rather than nothing.
    """
    candidates = tuple(candidate_formats)
    if not candidates:
        return None
    for output_format in _PREFERRED_FORMATS_BY_PLATFORM.get(sys.platform, ()):
        if output_format in candidates:
            return output_format
    return candidates[0]


def _uti_mime_converter_class():
    """Qt's macOS MIME-to-UTI converter, or None where it does not apply."""
    base = getattr(QtGui, "QUtiMimeConverter", None)
    if base is None:
        return None

    class VectorUtiMimeConverter(base):
        """Publish Hyde's vector types under the identifiers macOS knows.

        Qt maps a MIME type it does not recognise onto a private pasteboard
        flavour, which no application outside Qt can read, so vector bytes were
        on the clipboard and invisible. Naming the platform's own identifier is
        what makes them pasteable -- and the reverse direction lets Hyde read a
        vector someone else copied.
        """

        def utiForMime(self, mime):
            return _UTI_FOR_MIME_TYPE.get(str(mime or ""), "")

        def mimeForUti(self, uti):
            wanted = str(uti or "")
            for mime_type, mapped in _UTI_FOR_MIME_TYPE.items():
                if mapped == wanted:
                    return mime_type
            return ""

        def canConvert(self, mime, uti):
            return bool(uti) and self.utiForMime(mime) == str(uti)

        def convertFromMime(self, mime, data, uti):
            del mime, uti
            if isinstance(data, QtCore.QByteArray):
                return [data]
            if isinstance(data, (bytes, bytearray, memoryview)):
                return [QtCore.QByteArray(bytes(data))]
            return []

        def convertToMime(self, mime, data, uti):
            del mime, uti
            return QtCore.QByteArray(b"".join(bytes(chunk) for chunk in data))

        def count(self, mimeData):
            del mimeData
            return 1

    return VectorUtiMimeConverter


def register_clipboard_converters():
    """Teach this platform's clipboard about Hyde's vector types.

    Idempotent, and does nothing on a platform whose clipboard is MIME-typed
    already and so needs no translation.
    """
    if _REGISTERED_CONVERTERS:
        return tuple(_REGISTERED_CONVERTERS)
    converter_class = _uti_mime_converter_class()
    if converter_class is None:
        return ()
    try:
        _REGISTERED_CONVERTERS.append(converter_class())
    except Exception:
        LOGGER.exception(
            "Could not register a clipboard converter for Hyde's vector types; "
            "a copied vector will only paste into Qt applications."
        )
        return ()
    return tuple(_REGISTERED_CONVERTERS)


def registered_clipboard_converters():
    """The converters this process is holding registered."""
    return tuple(_REGISTERED_CONVERTERS)
