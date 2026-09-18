# -*- coding: utf-8 -*-
"""
Pure Python SVG Barcode Generator for Thermal Label Printing.
Supports: Code 128, EAN-13, EAN-8, UPC-A, and Code 39.

Zero external binary dependencies (no Cairo, no renderPM, no reportlab).
Outputs crisp vector SVG suitable for 203 DPI, 300 DPI, and 600 DPI thermal printers.
"""

import base64
import html
import re

# ----------------------------------------------------------------------
# 1. CODE 128 ENCODING TABLE (107 patterns, index 0 to 106)
# Each pattern is a tuple of 6 bar/space widths (e.g. (2, 1, 2, 2, 2, 2))
# Sum of widths is always 11 modules (Stop pattern is 13 modules).
# ----------------------------------------------------------------------
CODE128_PATTERNS = [
    (2, 1, 2, 2, 2, 2), (2, 2, 2, 1, 2, 2), (2, 2, 2, 2, 2, 1), (1, 2, 1, 2, 2, 3),
    (1, 2, 1, 3, 2, 2), (1, 3, 1, 2, 2, 2), (1, 2, 2, 2, 1, 3), (1, 2, 2, 3, 1, 2),
    (1, 3, 2, 2, 1, 2), (2, 2, 1, 2, 1, 3), (2, 2, 1, 3, 1, 2), (2, 3, 1, 2, 1, 2),
    (1, 1, 2, 2, 3, 2), (1, 2, 2, 1, 3, 2), (1, 2, 2, 2, 3, 1), (1, 1, 3, 2, 2, 2),
    (1, 2, 3, 1, 2, 2), (1, 2, 3, 2, 2, 1), (2, 2, 3, 2, 1, 1), (2, 2, 1, 1, 3, 2),
    (2, 2, 1, 2, 3, 1), (2, 1, 3, 2, 1, 2), (2, 2, 3, 1, 1, 2), (3, 1, 2, 1, 3, 1),
    (3, 1, 1, 2, 2, 2), (3, 2, 1, 1, 2, 2), (3, 2, 1, 2, 2, 1), (3, 1, 2, 2, 1, 2),
    (3, 2, 2, 1, 1, 2), (3, 2, 2, 2, 1, 1), (2, 1, 2, 1, 2, 3), (2, 1, 2, 3, 2, 1),
    (2, 3, 2, 1, 2, 1), (1, 1, 1, 3, 2, 3), (1, 3, 1, 1, 2, 3), (1, 3, 1, 3, 2, 1),
    (1, 1, 2, 3, 1, 3), (1, 3, 2, 1, 1, 3), (1, 3, 2, 3, 1, 1), (2, 1, 1, 3, 1, 3),
    (2, 3, 1, 1, 1, 3), (2, 3, 1, 3, 1, 1), (1, 1, 2, 1, 3, 3), (1, 1, 2, 3, 3, 1),
    (1, 3, 2, 1, 3, 1), (1, 1, 3, 1, 2, 3), (1, 1, 3, 3, 2, 1), (1, 3, 3, 1, 2, 1),
    (3, 1, 3, 1, 2, 1), (2, 1, 1, 3, 3, 1), (2, 3, 1, 1, 3, 1), (2, 1, 3, 1, 1, 3),
    (2, 1, 3, 3, 1, 1), (2, 1, 3, 1, 3, 1), (3, 1, 1, 1, 2, 3), (3, 1, 1, 3, 2, 1),
    (3, 3, 1, 1, 2, 1), (3, 1, 2, 1, 1, 3), (3, 1, 2, 3, 1, 1), (3, 3, 2, 1, 1, 1),
    (3, 1, 4, 1, 1, 1), (2, 2, 1, 4, 1, 1), (4, 3, 1, 1, 1, 1), (1, 1, 1, 2, 2, 4),
    (1, 1, 1, 4, 2, 2), (1, 2, 1, 1, 2, 4), (1, 2, 1, 4, 2, 1), (1, 4, 1, 1, 2, 2),
    (1, 4, 1, 2, 2, 1), (1, 1, 2, 2, 1, 4), (1, 1, 2, 4, 1, 2), (1, 2, 2, 1, 1, 4),
    (1, 2, 2, 4, 1, 1), (1, 4, 2, 1, 1, 2), (1, 4, 2, 2, 1, 1), (2, 4, 1, 2, 1, 1),
    (2, 2, 1, 1, 1, 4), (4, 1, 3, 1, 1, 1), (2, 4, 1, 1, 1, 2), (1, 3, 4, 1, 1, 1),
    (1, 1, 1, 2, 4, 2), (1, 2, 1, 1, 4, 2), (1, 2, 1, 2, 4, 1), (1, 1, 4, 2, 1, 2),
    (1, 2, 4, 1, 1, 2), (1, 2, 4, 2, 1, 1), (4, 1, 1, 2, 1, 2), (4, 2, 1, 1, 1, 2),
    (4, 2, 1, 2, 1, 1), (2, 1, 2, 1, 4, 1), (2, 1, 4, 1, 2, 1), (4, 1, 2, 1, 2, 1),
    (1, 1, 1, 1, 4, 3), (1, 1, 1, 3, 4, 1), (1, 3, 1, 1, 4, 1), (1, 1, 4, 1, 1, 3),
    (1, 1, 4, 3, 1, 1), (4, 1, 1, 1, 1, 3), (4, 1, 1, 3, 1, 1), (1, 1, 3, 1, 4, 1),
    (1, 1, 4, 1, 3, 1), (3, 1, 1, 1, 4, 1), (4, 1, 1, 1, 3, 1), (2, 1, 1, 4, 1, 2),
    (2, 1, 1, 2, 1, 4), (2, 1, 1, 2, 3, 2), (2, 3, 3, 1, 1, 1, 2),  # Stop pattern (7 entries)
]

START_B = 104
STOP = 106


def _encode_code128(text):
    """Encode ASCII string into Code 128 bit pattern."""
    if not text:
        text = "0000"
    codes = [START_B]
    for ch in text:
        val = ord(ch) - 32
        if 0 <= val <= 95:
            codes.append(val)
        else:
            codes.append(0)  # fallback space

    # Calculate checksum: (start + sum(i * val)) % 103
    checksum = codes[0] + sum(i * val for i, val in enumerate(codes[1:], 1))
    codes.append(checksum % 103)
    codes.append(STOP)

    # Convert code patterns into module sequences
    modules = []
    for code in codes:
        pattern = CODE128_PATTERNS[code]
        # Alternate bar and space
        is_bar = True
        for width in pattern:
            modules.extend([1 if is_bar else 0] * width)
            is_bar = not is_bar
    return modules


# ----------------------------------------------------------------------
# 2. EAN-13 & UPC-A ENCODING
# ----------------------------------------------------------------------
EAN_L = [
    "0001101", "0011001", "0010011", "0111101", "0100011",
    "0110001", "0101111", "0111011", "0110111", "0001011"
]
EAN_G = [
    "0100111", "0110011", "0011011", "0100001", "0011101",
    "0111001", "0000101", "0010001", "0001001", "0010111"
]
EAN_R = [
    "1110010", "1100110", "1101100", "1000010", "1011100",
    "1001110", "1010000", "1000100", "1001000", "1110100"
]
EAN_FIRST_PARITY = [
    "LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
    "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"
]


def _calc_ean_check_digit(digits):
    """Compute modulo 10 checksum for EAN/UPC."""
    total = sum(d * (3 if i % 2 == 1 else 1) for i, d in enumerate(reversed(digits)))
    return (10 - (total % 10)) % 10


def _encode_ean13(text):
    """Encode 12 or 13 digits into EAN-13 bit pattern."""
    digits = [int(c) for c in re.sub(r'\D', '', text)]
    if len(digits) < 12:
        digits = [0] * (12 - len(digits)) + digits
    elif len(digits) > 13:
        digits = digits[:13]

    if len(digits) == 12:
        check = _calc_ean_check_digit(digits)
        digits.append(check)

    first = digits[0]
    left_digits = digits[1:7]
    right_digits = digits[7:13]
    parity = EAN_FIRST_PARITY[first]

    bits = "101"  # Start guard
    for d, p in zip(left_digits, parity):
        bits += EAN_L[d] if p == 'L' else EAN_G[d]
    bits += "01010"  # Center guard
    for d in right_digits:
        bits += EAN_R[d]
    bits += "101"  # End guard

    return [int(b) for b in bits]


def _encode_ean8(text):
    """Encode 7 or 8 digits into EAN-8 bit pattern."""
    digits = [int(c) for c in re.sub(r'\D', '', text)]
    if len(digits) < 7:
        digits = [0] * (7 - len(digits)) + digits
    elif len(digits) > 8:
        digits = digits[:8]

    if len(digits) == 7:
        total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
        check = (10 - (total % 10)) % 10
        digits.append(check)

    left_digits = digits[:4]
    right_digits = digits[4:]

    bits = "101"
    for d in left_digits:
        bits += EAN_L[d]
    bits += "01010"
    for d in right_digits:
        bits += EAN_R[d]
    bits += "101"

    return [int(b) for b in bits]


# ----------------------------------------------------------------------
# 3. CODE 39 ENCODING
# ----------------------------------------------------------------------
CODE39_PATTERNS = {
    '0': '000110100', '1': '100100001', '2': '001100001', '3': '101100000',
    '4': '000110001', '5': '100110000', '6': '001110000', '7': '000100101',
    '8': '100100100', '9': '001100100', 'A': '100001001', 'B': '001001001',
    'C': '101001000', 'D': '000011001', 'E': '100011000', 'F': '001011000',
    'G': '000001101', 'H': '100001100', 'I': '001001100', 'J': '000011100',
    'K': '100000011', 'L': '001000011', 'M': '101000010', 'N': '000010011',
    'O': '100010010', 'P': '001010010', 'Q': '000000111', 'R': '100000110',
    'S': '001000110', 'T': '000010110', 'U': '110000001', 'V': '011000001',
    'W': '111000000', 'X': '010010001', 'Y': '110010000', 'Z': '011010000',
    '-': '010000101', '.': '110000100', ' ': '011000100', '*': '010010100',
    '$': '010101000', '/': '010100010', '+': '010001010', '%': '000101010',
}


def _encode_code39(text):
    """Encode string in Code 39 (wide bar = 3 units, narrow bar = 1 unit)."""
    text = '*' + text.upper() + '*'
    modules = []
    for ch in text:
        pattern = CODE39_PATTERNS.get(ch, CODE39_PATTERNS['-'])
        # Pattern is 9 characters: b s b s b s b s b
        for i, val in enumerate(pattern):
            is_bar = (i % 2 == 0)
            width = 3 if val == '1' else 1
            modules.extend([1 if is_bar else 0] * width)
        # Inter-character space (narrow)
        modules.append(0)
    return modules


# ----------------------------------------------------------------------
# 4. MAIN SVG GENERATOR
# ----------------------------------------------------------------------
def generate_barcode_svg(
    text,
    barcode_type='code128',
    height_mm=10.0,
    module_width_mm=0.33,
    quiet_zone_modules=10,
    show_text=False,
    font_size=9,
):
    """
    Generate clean, vector SVG barcode string.
    
    :param text: Value to encode
    :param barcode_type: 'code128', 'ean13', 'ean8', 'upca', 'code39'
    :param height_mm: Barcode height in mm
    :param module_width_mm: Base narrow bar width in mm (default 0.33mm / ~1.25px at 96dpi)
    :param quiet_zone_modules: Quiet zone width in modules (default 10)
    :param show_text: Include text line beneath barcode
    :param font_size: Font size for text if show_text is True
    :return: SVG markup string
    """
    raw_text = (text or "").strip()
    btype = (barcode_type or "code128").lower()

    if btype in ('ean13', 'ean-13'):
        modules = _encode_ean13(raw_text)
    elif btype in ('upca', 'upc-a'):
        modules = _encode_ean13('0' + raw_text if len(raw_text) == 11 else raw_text)
    elif btype in ('ean8', 'ean-8'):
        modules = _encode_ean8(raw_text)
    elif btype in ('code39', 'code-39'):
        modules = _encode_code39(raw_text)
    else:  # code128 default
        modules = _encode_code128(raw_text)

    # Pad with quiet zones
    full_modules = [0] * quiet_zone_modules + modules + [0] * quiet_zone_modules
    total_modules = len(full_modules)

    # Scale: use units in mm or viewBox
    bar_height = height_mm
    total_height = bar_height + (3.5 if show_text else 0.0)
    total_width = total_modules * module_width_mm

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {total_width:.2f} {total_height:.2f}" '
        f'width="{total_width:.2f}mm" height="{total_height:.2f}mm" '
        f'shape-rendering="crispEdges">'
    ]
    # Background
    svg_parts.append(f'<rect width="100%" height="100%" fill="#ffffff"/>')

    # Draw continuous bar rects (group consecutive 1s to minimize SVG elements)
    x = 0
    i = 0
    while i < total_modules:
        if full_modules[i] == 1:
            start_i = i
            while i < total_modules and full_modules[i] == 1:
                i += 1
            width = (i - start_i) * module_width_mm
            pos_x = start_i * module_width_mm
            svg_parts.append(
                f'<rect x="{pos_x:.2f}" y="0" width="{width:.2f}" height="{bar_height:.2f}" fill="#000000"/>'
            )
        else:
            i += 1

    if show_text:
        escaped_text = html.escape(raw_text)
        text_y = bar_height + 2.8
        center_x = total_width / 2.0
        svg_parts.append(
            f'<text x="{center_x:.2f}" y="{text_y:.2f}" '
            f'font-family="monospace, Arial, sans-serif" font-size="{font_size}px" '
            f'font-weight="bold" text-anchor="middle" fill="#000000">{escaped_text}</text>'
        )

    svg_parts.append('</svg>')
    return "".join(svg_parts)


def generate_barcode_data_uri(text, barcode_type='code128', **kwargs):
    """Return base64 data URI string for <img> tag embedding."""
    svg = generate_barcode_svg(text, barcode_type=barcode_type, **kwargs)
    b64 = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    return f"data:image/svg+xml;base64,{b64}"


# ----------------------------------------------------------------------
# 5. ZPL GENERATOR (Zebra Browser Print — direct/silent printing)
#
# Each ^B command takes its parameters in a slightly different order in
# Zebra's own ZPL II reference, so a small per-type builder is simpler and
# safer than trying to force one shared format string.
# ----------------------------------------------------------------------
_ZPL_BARCODE_BUILDERS = {
    'code128': lambda h, mod, show_text: f"^BY{mod}\n^BCN,{h},{'Y' if show_text else 'N'},N,N",
    'ean13': lambda h, mod, show_text: f"^BY{mod}\n^BEN,{h},{'Y' if show_text else 'N'},N",
    'ean8': lambda h, mod, show_text: f"^BY{mod}\n^B8N,{h},{'Y' if show_text else 'N'},N",
    'upca': lambda h, mod, show_text: f"^BY{mod}\n^BUN,{h},{'Y' if show_text else 'N'},N,N",
    'code39': lambda h, mod, show_text: f"^BY{mod}\n^B3N,N,{h},{'Y' if show_text else 'N'},N",
}


def _zpl_escape(text):
    """^ and ~ start ZPL commands, so free-text product names/SKUs must
    never be allowed to inject them into the command stream."""
    return (text or "").replace("^", "'").replace("~", "-").replace("\\", "/")[:120]


def _mm_to_dots(mm, dpi):
    return max(1, int(round(mm * dpi / 25.4)))


def build_zpl_label(item, preset, currency_symbol, company_name, dpi=203):
    """
    Build one ZPL ^XA...^XZ form for a single physical label, sized to the
    preset's label_width/label_height.

    Deliberately ignores the preset's column count: Zebra desktop printers
    (like the ZD410) feed one die-cut label at a time, never a multi-column
    roll, so 'columns' is only meaningful for the HTML/browser-print path
    below, which this is an alternative to, not a wrapper around.
    """
    w = _mm_to_dots(preset.label_width, dpi)
    h = _mm_to_dots(preset.label_height, dpi)
    margin_l = _mm_to_dots(preset.margin_left, dpi)
    margin_r = _mm_to_dots(preset.margin_right, dpi)
    margin_t = _mm_to_dots(preset.margin_top, dpi)
    margin_b = _mm_to_dots(preset.margin_bottom, dpi)
    content_w = max(1, w - margin_l - margin_r)

    font_mm = {'small': 2.2, 'normal': 2.75, 'large': 3.5}.get(preset.font_size, 2.75)
    font_h = _mm_to_dots(font_mm, dpi)
    font_h_meta = max(14, int(font_h * 0.75))
    font_h_price = int(font_h * 1.25)
    module_dots = max(2, _mm_to_dots(0.25, dpi))

    align = {'left': 'L', 'center': 'C', 'right': 'R'}.get(preset.text_align, 'C')

    lines = ["^XA", "^MMT", f"^PW{w}", f"^LL{h}", "^LH0,0", "^CI28"]
    y = margin_t

    top_items = []
    if preset.show_company_name and company_name:
        top_items.append(company_name)
    if preset.show_brand and item.get('brand'):
        top_items.append(item['brand'])
    if top_items:
        text = _zpl_escape(" - ".join(top_items))
        lines.append(f"^FO{margin_l},{y}^A0N,{font_h_meta},{font_h_meta}"
                     f"^FB{content_w},1,0,{align},0^FD{text}^FS")
        y += font_h_meta + 6

    if preset.show_product_name:
        text = _zpl_escape(item.get('product_name'))
        lines.append(f"^FO{margin_l},{y}^A0N,{font_h},{font_h}"
                     f"^FB{content_w},2,0,{align},0^FD{text}^FS")
        y += (font_h * 2) + 10

    barcode_val = item.get('barcode') or (item.get('sku') if preset.barcode_fallback == 'sku' else '')
    if preset.show_barcode and barcode_val:
        barcode_h = _mm_to_dots(preset.barcode_height, dpi)
        builder = _ZPL_BARCODE_BUILDERS.get(preset.barcode_type, _ZPL_BARCODE_BUILDERS['code128'])
        lines.append(f"^FO{margin_l},{y}")
        lines.append(builder(barcode_h, module_dots, preset.show_barcode_text))
        lines.append(f"^FD{_zpl_escape(barcode_val)}^FS")
        y += barcode_h + (30 if preset.show_barcode_text else 8)

    bottom_y = max(y, h - margin_b - font_h_meta)
    if preset.show_sku and item.get('sku'):
        text = _zpl_escape(f"SKU: {item['sku']}")
        lines.append(f"^FO{margin_l},{bottom_y}^A0N,{font_h_meta},{font_h_meta}^FD{text}^FS")
    if preset.show_price:
        uom_str = f"/{item.get('uom')}" if preset.show_uom and item.get('uom') else ""
        text = _zpl_escape(f"{currency_symbol} {item.get('price', 0):,.2f}{uom_str}")
        lines.append(f"^FO0,{bottom_y}^A0N,{font_h_price},{font_h_price}"
                     f"^FB{w - margin_r},1,0,R,0^FD{text}^FS")

    lines.append("^XZ")
    return "\n".join(lines)


def build_zpl_document(items, preset, currency_symbol, company_name):
    """Concatenate one ZPL form per label; Browser Print sends it as a single job."""
    dpi = int(preset.browserprint_dpi or 203)
    return "\n".join(
        build_zpl_label(item, preset, currency_symbol, company_name, dpi=dpi)
        for item in items
    )
