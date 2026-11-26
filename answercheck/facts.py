"""Normalize explicit wording variants for literal fact checks."""

import re


_DIGITS = "0123456789"
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９．", _DIGITS + ".")
_CHINESE_DIGITS = dict(zip("零〇一二两三四五六七八九", (0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
_CHINESE_PLACES = {"十": 10, "百": 100, "千": 1000}
_UNIT_EQUIVALENTS = {"日": "天", "块": "元", "块钱": "元", "工作日": "个工作日"}
_SPACE = r"[ \t\u3000]*"
_UNITS = r"个工作日|工作日|个月|小时|积分|块钱|天|日|年|元|块"
_CHINESE_NUMERALS = f"{''.join(_CHINESE_DIGITS)}十百千万"
_NUMBER_CHARS = f"0-9{_CHINESE_NUMERALS}"
_NUMBER = (
    rf"(?:[0-9]+(?:[,，][0-9]{{3}})+|[{_NUMBER_CHARS}]+)"
    rf"(?:{_SPACE}[.点點]{_SPACE}[{_NUMBER_CHARS}]+)*"
)
_QUANTITY = re.compile(
    r"(?:(?<![0-9.\-－−])[ \t\u3000]+)?"
    rf"(?P<number>{_NUMBER}){_SPACE}(?P<unit>{_UNITS})"
)
_SMALL_CHANGE = rf"{_SPACE}[{_NUMBER_CHARS}]+{_SPACE}(?:角|毛|分(?!钟|之))"
# 「一块五」的尾数属于金额。「1元1积分」的后一组数字有自己的单位。
_SHORT_CHANGE = rf"{_SPACE}[{_NUMBER_CHARS}]+(?![{_NUMBER_CHARS}]|{_SPACE}(?:{_UNITS}))"
_AMOUNT = re.compile(
    rf"(?:[-－−+＋负]{_SPACE})?{_NUMBER}{_SPACE}(?:元|块钱|块)"
    rf"(?:(?:{_SMALL_CHANGE})+|{_SHORT_CHANGE})?"
)


def _chinese_integer(number):
    total = section = 0
    digit = None
    for char in number:
        if char in _CHINESE_DIGITS:
            if digit not in (None, 0):
                # 连续数字可能表示范围，例如「一两天」。
                return None
            digit = _CHINESE_DIGITS[char]
        elif char == "万":
            total += (section + (digit or 0)) * 10000
            section = 0
            digit = None
        else:
            section += (1 if digit is None else digit) * _CHINESE_PLACES[char]
            digit = None
    return total + section + (digit or 0)


def normalize_numbers(text):
    """Use ASCII numbers and consistent units for supported quantities."""
    def normalize_quantity(match):
        number, unit = match.group("number", "unit")
        if re.fullmatch(rf"[{_CHINESE_NUMERALS}]+", number):
            integer = _chinese_integer(number)
            if integer is None:
                return match[0]
            number = str(integer)
        elif not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", number):
            return match[0]
        return number + _UNIT_EQUIVALENTS.get(unit, unit)

    return _QUANTITY.sub(normalize_quantity, text.translate(_FULLWIDTH_DIGITS))


def normalize_synonyms(text, synonyms):
    """Replace explicitly listed aliases once, preferring longer phrases."""
    if not synonyms:
        return text
    aliases = sorted(synonyms, key=len, reverse=True)
    pattern = "|".join(re.escape(alias) for alias in aliases)
    return re.sub(pattern, lambda match: synonyms[match[0]], text)


def normalize_fact_text(text, synonyms):
    return normalize_numbers(normalize_synonyms(text, synonyms))


def contains_fact(text, phrase):
    """Match normalized text using complete quantities and amounts."""
    pattern = re.escape(phrase)
    if phrase and phrase[0] in _DIGITS:
        pattern = r"(?<![0-9.\-－−])" + pattern
    if phrase and phrase[-1] in _DIGITS:
        pattern += r"(?![0-9]|\.[0-9])"
    if not _AMOUNT.search(phrase):
        return re.search(pattern, text) is not None

    amounts = [amount.span() for amount in _AMOUNT.finditer(text)]
    return any(
        all(not (start < match.start() < end or start < match.end() < end)
            for start, end in amounts)
        for match in re.finditer(pattern, text)
    )
