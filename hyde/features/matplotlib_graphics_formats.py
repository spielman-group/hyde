"""Matplotlib export formats available to Hyde.

GENERATED FILE -- do not edit by hand.

Regenerate with `python scripts/regenerate_graphics_formats.py` whenever the
matplotlib dependency changes. Hyde reads this table instead of querying
matplotlib at runtime, because that query imports pyplot and resolves an
interactive backend, which the GUI process must not do.

Generated against matplotlib 3.11.1.
"""

GRAPHICS_EXPORT_FILETYPES = {
    'avif': 'AV1 Image File Format',
    'eps': 'Encapsulated Postscript',
    'gif': 'Graphics Interchange Format',
    'jpeg': 'Joint Photographic Experts Group',
    'jpg': 'Joint Photographic Experts Group',
    'pdf': 'Portable Document Format',
    'pgf': 'PGF code for LaTeX',
    'png': 'Portable Network Graphics',
    'ps': 'Postscript',
    'raw': 'Raw RGBA bitmap',
    'rgba': 'Raw RGBA bitmap',
    'svg': 'Scalable Vector Graphics',
    'svgz': 'Scalable Vector Graphics',
    'tif': 'Tagged Image File Format',
    'tiff': 'Tagged Image File Format',
    'webp': 'WebP Image Format',
}
