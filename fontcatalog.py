"""
Font catalogue for the caption text drawn on photo borders.

Why this exists
---------------
Before this module the fonts were two hardcoded filenames. Now there are three
independently choosable text roles - the EXIF heading, the EXIF body, and the
optional custom text - and several of the bundled families are **variable
fonts** with a `wght` axis rather than separate Regular/Bold files.

That second point drives the design. A variable font loaded without selecting an
axis position renders at its *default* instance, which for Cormorant Garamond is
Light, not Regular. So a family is not "a filename"; it is a filename plus a
named weight instance per role. `FontFamily` carries both, and `spec()` hands
out the `(filename, variant_index, weight_name)` triple that `text.py` and
`border.py` consume.

`display_only` families (the scripts) are excluded from the EXIF pickers on
purpose: a three-line technical caption set in Great Vibes is unreadable at
caption size. They remain available for the custom text, which is the signature
/ credit line they suit.

Licences for every bundled family live in `fonts/licenses/`. The `-VF` files are
unmodified upstream releases - weights are chosen at render time, nothing is
instanced or subset, so the OFL Reserved Font Name clause is not engaged.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class FontFamily:
    """One selectable family.

    Attributes:
        key:            Stable identifier persisted in settings and accepted on
                        the CLI. Never rename one of these without a migration -
                        `find()` falls back to the default on an unknown key, so a
                        rename silently resets the user's choice.
        label:          Human-readable name shown in the GUI.
        regular_file:   Font file in the fonts directory used for body text.
        bold_file:      Font file used for the EXIF heading. Equal to
                        regular_file for variable fonts (the weight differs, not
                        the file) and for single-weight families.
        regular_weight: Named variation instance for body text, or None for a
                        static font.
        bold_weight:    Named variation instance for the heading, or None.
        display_only:   True for families unsuitable for the multi-line EXIF
                        caption. Offered for the custom text only.
        note:           Optional one-liner surfaced as a GUI tooltip.
    """
    key: str
    label: str
    regular_file: str
    bold_file: str
    regular_weight: Optional[str] = None
    bold_weight: Optional[str] = None
    display_only: bool = False
    note: str = ""


# Order here is the order shown in the GUI combo boxes.
FAMILIES: List[FontFamily] = [
    FontFamily(
        key="roboto", label="Roboto (default)",
        regular_file="Roboto-Regular.ttf", bold_file="Roboto-Medium.ttf",
        note="The original PhotoBorder font. Neutral grotesque.",
    ),
    FontFamily(
        key="ebgaramond", label="EB Garamond",
        regular_file="EBGaramond-VF.ttf", bold_file="EBGaramond-VF.ttf",
        regular_weight="Regular", bold_weight="SemiBold",
        note="Classical book serif. Low contrast, warm, prints well small.",
    ),
    FontFamily(
        key="cormorant", label="Cormorant Garamond",
        regular_file="CormorantGaramond-VF.ttf", bold_file="CormorantGaramond-VF.ttf",
        regular_weight="Regular", bold_weight="SemiBold",
        note="High-contrast display Garamond. Elegant; delicate at small sizes.",
    ),
    FontFamily(
        key="baskerville", label="Libre Baskerville",
        regular_file="LibreBaskerville-VF.ttf", bold_file="LibreBaskerville-VF.ttf",
        regular_weight="Regular", bold_weight="Bold",
        note="Sturdy transitional serif with a large x-height. Very legible.",
    ),
    FontFamily(
        key="lora", label="Lora",
        regular_file="Lora-VF.ttf", bold_file="Lora-VF.ttf",
        regular_weight="Regular", bold_weight="Bold",
        note="Contemporary brushed serif. Reads cleanly at caption size.",
    ),
    FontFamily(
        key="dancingscript", label="Dancing Script",
        regular_file="DancingScript-VF.ttf", bold_file="DancingScript-VF.ttf",
        regular_weight="Regular", bold_weight="Bold",
        display_only=True,
        note="Casual script. Custom text only - unreadable as EXIF body text.",
    ),
    FontFamily(
        key="greatvibes", label="Great Vibes",
        regular_file="GreatVibes-Regular.ttf", bold_file="GreatVibes-Regular.ttf",
        display_only=True,
        note="Formal copperplate script. Single weight. Custom text only.",
    ),
    FontFamily(
        key="parisienne", label="Parisienne",
        regular_file="Parisienne-Regular.ttf", bold_file="Parisienne-Regular.ttf",
        display_only=True,
        note="Light handwritten script. Single weight. Custom text only.",
    ),
]

DEFAULT_KEY = "roboto"
DEFAULT_TEXT_KEY = "ebgaramond"

_BY_KEY = {f.key: f for f in FAMILIES}


def all_families() -> List[FontFamily]:
    """Every family, in display order. Suitable for the custom-text picker."""
    return list(FAMILIES)


def caption_families() -> List[FontFamily]:
    """Families suitable for the multi-line EXIF caption (scripts excluded)."""
    return [f for f in FAMILIES if not f.display_only]


def find(key: str, default: str = DEFAULT_KEY) -> FontFamily:
    """Look up a family by key, falling back to `default`.

    Never raises. An unknown key (a hand-edited settings file, a stale saved
    value, a typo on the CLI) degrades to the default family rather than
    breaking a batch part-way through - consistent with how settings are
    treated everywhere else in this suite.
    """
    fam = _BY_KEY.get((key or "").strip().lower())
    if fam is not None:
        return fam
    return _BY_KEY.get(default, FAMILIES[0])


def spec(key: str, bold: bool = False, default: str = DEFAULT_KEY) -> Tuple[str, int, Optional[str]]:
    """Return the `(filename, variant_index, weight_name)` triple for a role.

    `filename` is relative to the fonts directory - callers join it themselves,
    matching the existing `fontdir` convention in `core.process_image`.
    """
    fam = find(key, default=default)
    if bold:
        return (fam.bold_file, 0, fam.bold_weight)
    return (fam.regular_file, 0, fam.regular_weight)


def keys() -> List[str]:
    """All family keys, for CLI `choices=`."""
    return [f.key for f in FAMILIES]


def caption_keys() -> List[str]:
    """Family keys valid for the EXIF caption, for CLI `choices=`."""
    return [f.key for f in caption_families()]
