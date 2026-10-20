import re


def parse_number(value, default=0.0):
    """'12.5', '$12.50', '448 ounces', 12 -> float; anything else -> default."""
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group()) if match else default


def format_zip(zip_code):
    digits = re.sub(r"\D", "", str(zip_code or ""))
    if len(digits) == 9:
        return digits[:5] + "-" + digits[5:]
    if 0 < len(digits) < 5:
        return digits.zfill(5)
    return digits[:5] if len(digits) >= 5 else ""
