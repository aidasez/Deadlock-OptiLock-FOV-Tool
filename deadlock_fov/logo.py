"""The ASCII logo, drawn the way archey3 draws its distro art.

Two tones, mirroring archey3's own ``{c1}``/``{c2}`` split: tone 1 is the bold
colour, tone 2 the non-bold one.

Only U+2588 FULL BLOCK and spaces are used - deliberately. Half blocks (``▄``
``▀``) only tile correctly when the line box is exactly one glyph tall, so they
fall apart at normal line spacing. Full blocks always fill their cell, so the
shape holds at any spacing. Each row is drawn at a fixed x, so uneven row
lengths are harmless.
"""

from __future__ import annotations

# Turned off: the info block stands on its own. Flip this to True to bring the
# logo back - nothing else needs to change.
SHOW_LOGO = False

_BLOCKS = "█"

# A padlock - deadlock, see. 24 columns wide: shackle rows 0-3 (tone 2), body
# rows 4-14 (tone 1), with a hollow keyhole punched through the body.
#
# The bore is wider than it is tall on purpose: monospace cells are about twice
# as tall as they are wide, so a shape that is square in *pixels* has to be
# wider than it is tall in *characters*.
LOGO: tuple[tuple[str, int], ...] = (
    ("      " + _BLOCKS * 12, 2),
    ("      " + _BLOCKS * 2 + " " * 8 + _BLOCKS * 2, 2),
    ("      " + _BLOCKS * 2 + " " * 8 + _BLOCKS * 2, 2),
    ("      " + _BLOCKS * 2 + " " * 8 + _BLOCKS * 2, 2),
    (_BLOCKS * 24, 1),
    (_BLOCKS * 24, 1),
    (_BLOCKS * 9 + " " * 6 + _BLOCKS * 9, 1),
    (_BLOCKS * 7 + " " * 10 + _BLOCKS * 7, 1),
    (_BLOCKS * 7 + " " * 10 + _BLOCKS * 7, 1),
    (_BLOCKS * 9 + " " * 6 + _BLOCKS * 9, 1),
    (_BLOCKS * 11 + " " * 2 + _BLOCKS * 11, 1),
    (_BLOCKS * 11 + " " * 2 + _BLOCKS * 11, 1),
    (_BLOCKS * 24, 1),
    (_BLOCKS * 24, 1),
)


def as_text() -> str:
    """Debug view: blocks as ``#``, spaces as ``.``, so the shape is readable."""
    return "\n".join(
        ("# " if tone == 2 else "#") + row.replace(_BLOCKS, "#").replace(" ", ".")
        for row, tone in LOGO
    )
