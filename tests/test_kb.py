import unittest
from pathlib import Path


class KnowledgeBaseTests(unittest.TestCase):
    def test_passage_numbers_and_body_boundaries(self):
        from answercheck.kb import load_kb

        kb_dir = Path(__file__).with_name("fixtures") / "kb"
        self.assertEqual(
            load_kb(kb_dir),
            {
                "returns#1": (
                    "青柚家电提供 7 天无理由退货。请保留包装。\n\n"
                    "自行寄回前请联系客服。"
                ),
                "returns#2": "退货运费需自理。",
                "warranty#1": "维修时请带购买凭证。",
            },
        )
