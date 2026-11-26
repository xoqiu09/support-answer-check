import json
import unittest
from pathlib import Path

from answercheck.facts import contains_fact, normalize_numbers, normalize_synonyms


class FactMatchingTests(unittest.TestCase):
    def test_normalizes_chinese_numerals_fullwidth_digits_and_units(self):
        examples = (
            ("七日内", "7天内"),
            ("十七 天", "17天"),
            ("２４　小时", "24小时"),
            ("十二个月", "12个月"),
            ("一百零二积分", "102积分"),
            ("两万零三百块钱", "20300元"),
            ("１块", "1元"),
            ("每百积分抵扣 1 元", "每100积分抵扣1元"),
            ("第 123 单，备注 123 1 天", "第 123 单，备注 123 1天"),
            ("３工作日", "3个工作日"),
            ("三个工作日", "3个工作日"),
            ("１．５ 元", "1.5元"),
            ("约一两天；一起处理。", "约一两天；一起处理。"),
            ("订单 １２３", "订单 123"),
        )
        for original, expected in examples:
            with self.subTest(original=original):
                self.assertEqual(normalize_numbers(original), expected)

    def test_matches_only_the_requested_number_and_unit(self):
        for answer, fact, expected in (
            ("不晚于七日", "7 天", True),
            ("十七日内", "7 天", False),
            ("三个工作日内", "三天", False),
            ("可抵扣 12.5 元", "5 元", False),
            ("可抵扣一块钱", "抵扣 1 元", True),
            ("可抵扣 21 元", "1 元", False),
            ("每实付零点一元获得一积分", "1 元", False),
            ("每实付零点 1 元获得一积分", "1 元", False),
            ("每百积分抵扣一块五", "抵扣 1 元", False),
            ("每百积分抵扣一块 五", "抵扣 1 元", False),
            ("每百积分抵扣 1 元 5 角", "抵扣 1 元", False),
            ("共支付 1,250 元", "250 元", False),
            ("差额为负 1 元", "1 元", False),
            ("每实付1元1积分", "1 元", True),
        ):
            with self.subTest(answer=answer, fact=fact):
                self.assertEqual(contains_fact(normalize_numbers(answer), normalize_numbers(fact)), expected)

    def test_uses_only_explicit_synonyms_and_keeps_negation(self):
        synonyms = {"确认身份": "核实身份", "证件": "凭证", "纸质证件": "纸质凭证"}
        self.assertEqual(normalize_synonyms("无需确认身份。纸质证件", synonyms), "无需核实身份。纸质凭证")
        self.assertEqual(normalize_synonyms("确认手机号码", synonyms), "确认手机号码")
        self.assertEqual(normalize_synonyms("确认身份", {}), "确认身份")


class HeldOutLabelsTests(unittest.TestCase):
    def test_heldout_labels_differ_from_literal_baseline(self):
        root = Path(__file__).resolve().parents[1]
        labels_text = (root / "data/heldout/labels.jsonl").read_text(encoding="utf-8")
        labels = {row["case_id"]: row for row in map(json.loads, labels_text.splitlines())}
        self.assertEqual(len(labels), 12)
        self.assertEqual(sum(row["verdict"] == "pass" for row in labels.values()), 6)
        baseline = json.loads((root / "reports/heldout-before.json").read_text(encoding="utf-8"))
        for bot in ("naive", "careful"):
            with self.subTest(bot=bot):
                cases = baseline[bot]["check"]["cases"]
                self.assertEqual({row["case_id"] for row in cases}, labels.keys())
                self.assertTrue(any(row["verdict"] != labels[row["case_id"]]["verdict"] for row in cases))
