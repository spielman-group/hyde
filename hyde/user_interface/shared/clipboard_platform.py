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

import sys

# Verified: a PDF put on the macOS pasteboard as `com.adobe.pdf` pastes into
# applications outside Qt. Linux is deliberately absent -- see
# issues/CLIPBOARD_REPRESENTATIONS.md, where establishing what a Linux selection
# already publishes is a deferred slice. Until that runs it takes the first
# candidate rather than a guess.
_PREFERRED_FORMATS_BY_PLATFORM = {
    "darwin": ("pdf",),
}


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
