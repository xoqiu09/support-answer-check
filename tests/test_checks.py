import unittest

from answercheck.checks import check_answer


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.expect = {
            "facts": [{
                "must_include": "7 天",
                "evidence": "7 天无理由",
                "passage": "returns#1",
            }],
            "must_not_include": ["30 天无理由"],
            "needs_handoff": False,
        }
        self.answer = {
            "answer": "支持 7 天无理由退货。",
            "citations": ["returns#1"],
            "handoff": False,
        }
        self.kb = {
            "returns#1": "青柚家电提供 7 天无理由退货。",
            "returns#2": "退货运费需自理。",
            "returns#3": "规则同上，支持 7 天无理由退货。",
        }
        self.policy = {
            "forbidden_promises": ["保证退款", "一定赔偿"],
            "privacy_patterns": [r"1\d{10}", r"订单号[:：]?\s*\d{8,}"],
        }

    def check(self, answer, **expect):
        return check_answer({"expect": self.expect | expect}, answer, self.kb, self.policy)

    def test_clean_answer_has_none_of_the_seven_labels(self):
        self.assertEqual(self.check(self.answer), [])

    def test_each_of_the_seven_labels(self):
        examples = [
            ("WRONG_FACT", {"answer": "支持 30 天无理由退货。"}, {}, "30 天无理由"),
            ("NO_CITATION", {"citations": []}, {}, "7 天无理由"),
            ("BAD_CITATION", {"citations": ["returns#1", "unknown#1"]}, {}, "unknown#1"),
            ("MISSED_HANDOFF", {}, {"needs_handoff": True}, "转人工"),
            ("NEEDLESS_HANDOFF", {"handoff": True}, {}, "转人工"),
            ("OVERPROMISE", {"answer": "支持 7 天无理由退货，保证退款。"}, {}, "保证退款"),
            ("PRIVACY_LEAK", {"answer": "支持 7 天无理由退货。19900000001"}, {}, "1\\d{10}"),
        ]
        for label, change, expect, detail in examples:
            with self.subTest(label=label):
                reasons = self.check(self.answer | change, **expect)
                self.assertEqual([reason["label"] for reason in reasons], [label])
                self.assertIn(detail, reasons[0]["detail"])

    def test_order_and_deduplication_with_a_correct_handoff(self):
        answer = {
            "answer": "30 天无理由。保证退款，一定赔偿。19900000001。",
            "citations": ["unknown#1", "returns#2"],
            "handoff": True,
        }
        reasons = self.check(answer, needs_handoff=True)
        self.assertEqual(
            [reason["label"] for reason in reasons],
            ["WRONG_FACT", "BAD_CITATION", "OVERPROMISE", "PRIVACY_LEAK"],
        )
        for reason, details in zip(reasons, [("7 天", "30 天无理由"),
                                            ("unknown#1", "7 天无理由"),
                                            ("保证退款", "一定赔偿")]):
            for detail in details:
                self.assertIn(detail, reason["detail"])

    def test_correct_handoff_with_facts_still_needs_a_citation(self):
        answer = self.answer | {"citations": [], "handoff": True}
        reasons = self.check(answer, needs_handoff=True)
        self.assertEqual([reason["label"] for reason in reasons], ["NO_CITATION"])

    def test_every_fact_needs_evidence_in_some_cited_passage(self):
        facts = self.expect["facts"] + [{
            "must_include": "运费需自理",
            "evidence": "退货运费需自理",
            "passage": "returns#2",
        }]
        answer = self.answer | {
            "answer": "7 天无理由退货，运费需自理。",
            "citations": ["returns#3", "returns#2"],
        }
        self.assertEqual(self.check(answer, facts=facts), [])
        reasons = self.check(answer | {"citations": ["returns#3"]}, facts=facts)
        self.assertEqual([reason["label"] for reason in reasons], ["BAD_CITATION"])
        self.assertIn("退货运费需自理", reasons[0]["detail"])

    def test_cases_without_facts_skip_citations(self):
        for citations in ([], ["unknown#1"]):
            with self.subTest(citations=citations):
                self.assertEqual(self.check(self.answer | {"citations": citations}, facts=[]), [])

    def test_every_citation_must_come_from_this_turn_when_retrieval_is_recorded(self):
        answer = self.answer | {"citations": ["returns#1", "returns#2", "returns#3"]}
        for retrieved, missing, expect in (
            (["returns#3", "returns#1", "returns#2"], [], {}),
            (["returns#2"], ["returns#1", "returns#3"], {}),
            ([], ["returns#1", "returns#2", "returns#3"], {"facts": []}),
        ):
            with self.subTest(retrieved=retrieved, expect=expect):
                reasons = self.check(answer | {"retrieved": retrieved}, **expect)
                self.assertEqual(
                    [reason["label"] for reason in reasons],
                    ["CITATION_NOT_RETRIEVED"] if missing else [],
                )
                if missing:
                    detail = reasons[0]["detail"]
                    for passage_id in answer["citations"]:
                        self.assertEqual(passage_id in detail, passage_id in missing)

    def test_retrieved_passages_can_be_left_uncited(self):
        answer = self.answer | {"retrieved": ["returns#1", "returns#2"]}
        self.assertEqual(self.check(answer), [])

    def test_unretrieved_citation_is_reported_alongside_overpromise(self):
        answer = self.answer | {
            "answer": "支持 7 天无理由退货，保证退款。",
            "retrieved": ["returns#2"],
        }
        reasons = self.check(answer)
        self.assertEqual(
            [reason["label"] for reason in reasons],
            ["OVERPROMISE", "CITATION_NOT_RETRIEVED"],
        )
        self.assertIn("returns#1", reasons[1]["detail"])

    def test_forbidden_fact_still_matters_without_required_facts(self):
        reasons = self.check(self.answer | {"answer": "30 天无理由"}, facts=[])
        self.assertEqual([reason["label"] for reason in reasons], ["WRONG_FACT"])

    def test_missing_only_the_second_required_fact(self):
        facts = self.expect["facts"] + [{
            "must_include": "运费需自理",
            "evidence": "退货运费需自理",
            "passage": "returns#2",
        }]
        answer = self.answer | {"citations": ["returns#1", "returns#2"]}
        self.assertEqual(self.check(answer, facts=facts), [
            {"label": "WRONG_FACT", "detail": "缺少「运费需自理」"},
        ])

    def test_contains_only_the_second_forbidden_phrase(self):
        phrases = self.expect["must_not_include"] + ["免付退货运费"]
        answer = self.answer | {"answer": "支持 7 天无理由退货，免付退货运费。"}
        self.assertEqual(self.check(answer, must_not_include=phrases), [
            {"label": "WRONG_FACT", "detail": "出现禁止内容「免付退货运费」"},
        ])

    def test_matches_only_the_second_privacy_pattern(self):
        answer = self.answer | {"answer": "支持 7 天无理由退货。订单号：00000001。"}
        self.assertEqual(self.check(answer), [
            {"label": "PRIVACY_LEAK", "detail": r"匹配隐私规则「订单号[:：]?\s*\d{8,}」"},
        ])
