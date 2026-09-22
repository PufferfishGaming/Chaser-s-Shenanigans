"""
Photo Exif extraction functions
"""
import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from PIL import Image
from PIL.ExifTags import TAGS


def clean_exif_text(value) -> str:
    """Strip control/format characters out of an EXIF string, then tidy spacing.

    Cameras NUL-pad the fixed-length ASCII EXIF fields, and `str.strip()` removes
    whitespace but NOT control characters, so those NULs used to reach the
    renderer. Whether they were *visible* depended entirely on the font: Roboto
    and EB Garamond map NUL to a zero-width glyph, while Cormorant Garamond,
    Libre Baskerville and Lora map it to a `.notdef` box - which is why the
    caption grew boxes in exactly three of the five EXIF fonts and looked like a
    font bug rather than a data bug.

    They also inflated the *measured* width (three NULs added 72-120px at size
    48), so the shrink-to-fit sizing was scaling real text down to make room for
    characters that were not supposed to be there.

    Every Unicode "other" category (Cc, Cf, Cs, Co, Cn) goes. Ones that are also
    whitespace become a space rather than vanishing, so a value that used a
    newline as a separator does not have its words run together. Runs of
    whitespace then collapse and the result is stripped.

    This is the single choke point: `ExifItem.__str__` calls it, so nothing can
    reach a font without passing through here.
    """
    if value is None:
        return ''
    if isinstance(value, bytes):
        # get_exif leaves undecodable bytes as bytes rather than raising; without
        # this they would render as the literal repr of the bytes object instead
        value = value.decode('utf-8', 'ignore')
    elif not isinstance(value, str):
        value = str(value)
    out = []
    for ch in value:
        if unicodedata.category(ch)[0] == 'C':
            # A control that is also whitespace (newline, tab, CR)
            out.append(' ' if ch.isspace() else '')
        else:
            out.append(ch)
    return ' '.join(''.join(out).split())

def format_shutter_speed(shutter_speed: str) -> str:
    """
    Convert a decimal value to a fraction display.
    Used to display shutter speed values.
    """
    try:
        fraction = Fraction(shutter_speed).limit_denominator()
        if fraction >= 1:
            # return f"{fraction.numerator}/{fraction.denominator}"
            return f"{fraction.numerator}"
        else:
            return f"1/{int(1/float(shutter_speed))}"
    except (ValueError, ZeroDivisionError):
        return shutter_speed

def format_focal_length(focal_length: str) -> str:
    """
    Round Focal Length
    """
    try:
        focal_length_dp = focal_length[::-1].find('.') #https://docs.python.org/dev/library/stdtypes.html#str.find
        if focal_length_dp >= 2: # Checks if the focal length has 2 decimal places or greater eg 24.878mm
            return round(float(focal_length), 2)
        else:
            # Round to a whole number when there is a single decimal place:
            # 24.0mm reads as 24mm.
            return round(float(focal_length))
    except ValueError:
        return focal_length

@dataclass
class ExifItem:
    tag: str
    data: str

    formatter = {
        'Make': 'Shot on {dataval}',
        'FocalLength': '{dataval}mm',
        'FNumber': 'f/{dataval}',
        'ISOSpeedRatings': 'ISO{dataval}',
        'ExposureTime': '{dataval} sec'
    }

    def __str__(self) -> str:
        if self.data is None or self.data == '':
            return ''
        # Clean BEFORE the emptiness test and before any formatting: a value of
        # nothing but NULs must collapse to '' rather than render the template
        # around it ("Shot on " with no camera).
        fmt_data = clean_exif_text(self.data)
        if not fmt_data:
            return ''

        # Deal with any special case data formatting
        if self.tag == 'ExposureTime':
           fmt_data = format_shutter_speed(fmt_data)

        # Deal with any special case data formatting
        if self.tag == 'FocalLength':
           fmt_data = format_focal_length(fmt_data)

        # Apply the string template formatting defined in self.formatter
        if self.tag in self.formatter:
            return self.formatter[self.tag].format(dataval=fmt_data)

        return fmt_data


def get_exif(img: Image) -> dict:
    """Load the exif data from an image.

    Args:
        img (Image): Pillow image object.

    Returns:
        dict: dictionary with exif data
    """
    exif_data = img._getexif()
    exif_dict = {
        'Make': '',
        'Model': '',
        'LensMake': '',
        'LensModel': '',
        'FNumber': '',
        'FocalLength': '',
        'ISOSpeedRatings': '',
        'ExposureTime': ''
    }

    if exif_data:
        # Iterate through the EXIF data and store it in the dictionary
        for tag_id in exif_data:
            tag = TAGS.get(tag_id, tag_id)
            data = exif_data.get(tag_id)

            if isinstance(data, bytes):
                try:
                    data = data.decode()
                except UnicodeDecodeError as e:
                    # print(f'Error decoding tag {tag}', e)
                    # Expect decoding errors, ust ignore as we don't need the exif these happen on.
                    pass

            exif_dict[tag] = ExifItem(tag, data)

    # Print the EXIF data dictionary
    # print(exif_dict)

    return exif_dict
