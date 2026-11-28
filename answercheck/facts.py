"""Normalize explicit wording variants for literal fact checks."""

import re
from fractions import Fraction


_DIGITS = "0123456789"
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９．", _DIGITS + ".")
_CHINESE_DIGITS = dict(zip("零〇一二两三四五六七八九", (0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
_CHINESE_DECIMAL_DIGITS = str.maketrans({digit: str(value) for digit, value in _CHINESE_DIGITS.items()})
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
_DURATION_UNITS = r"个工作日|工作日|个月|小时|天|日|年"
_WHOLE_DURATION_END = re.compile(rf"[0-9](?:{_DURATION_UNITS})\Z")
_SMALL_CHANGE = rf"{_SPACE}[{_NUMBER_CHARS}]+{_SPACE}(?:角|毛|分(?!钟|之))"
# 「一块五」的尾数属于金额。「1元1积分」的后一组数字有自己的单位。
_SHORT_CHANGE = rf"{_SPACE}[{_NUMBER_CHARS}]+(?![{_NUMBER_CHARS}]|{_SPACE}(?:{_UNITS}))"
AMOUNT_PATTERN = (
    rf"(?:(?P<amount_sign>[-－−+＋负]){_SPACE})?(?P<yuan>{_NUMBER}){_SPACE}(?:元|块钱|块)"
    rf"(?:(?P<small_change>(?:{_SMALL_CHANGE})+)|(?P<short_change>{_SHORT_CHANGE}))?"
)
_AMOUNT = re.compile(AMOUNT_PATTERN)


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


def _amount_number(number):
    number = re.sub(r"[\s,，]", "", number).replace("点", ".").replace("點", ".")
    whole, _, decimals = number.partition(".")
    if whole.isascii():
        whole_value = int(whole)
    elif all(char in _CHINESE_NUMERALS for char in whole):
        whole_value = _chinese_integer(whole)
    else:
        return None
    decimals = decimals.translate(_CHINESE_DECIMAL_DIGITS)
    if whole_value is None or (decimals and not decimals.isdecimal()):
        return None
    return Fraction(f"{whole_value}.{decimals}" if decimals else whole_value)


def amount_value(match):
    """Read a complete AMOUNT_PATTERN match as an exact number of yuan."""
    value = _amount_number(match["yuan"])
    if value is None:
        return None
    for part in re.findall(_SMALL_CHANGE, match["small_change"] or ""):
        change = _amount_number(part[:-1])
        if change is None:
            return None
        value += change / (100 if part[-1] == "分" else 10)
    if match["short_change"]:
        digits = match["short_change"].strip()
        change = _amount_number(digits)
        if change is None:
            return None
        value += change / 10 ** len(digits)
    return -value if match["amount_sign"] in ("-", "－", "−", "负") else value


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
    if _WHOLE_DURATION_END.search(phrase):
        # 「1年 半年内」中的「半」另起一个时长。
        pattern += rf"(?!半|{_SPACE}半(?!{_SPACE}(?:{_DURATION_UNITS})))"
    if not _AMOUNT.search(phrase):
        return re.search(pattern, text) is not None

    amounts = [amount.span() for amount in _AMOUNT.finditer(text)]
    return any(
        all(not (start < match.start() < end or start < match.end() < end)
            for start, end in amounts)
        for match in re.finditer(pattern, text)
    )
