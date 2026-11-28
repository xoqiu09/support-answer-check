import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import Mock, patch

from answercheck.__main__ import main
from answercheck.kb import load_kb
from answercheck.models import FakeModel, HttpChatModel
from answercheck.report import build_report

from .test_cli import ANSWERS, CASES, DATA, KB, read_jsonl


def chat_reply(content):
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


class ReplayTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.temp = Path(directory.name)
        self.run_args = ["run-bot", "--kb", str(KB), "--cases", str(CASES)]

    def test_fake_answers_round_trip_byte_for_byte(self):
        cases = read_jsonl(CASES)
        passages = load_kb(KB)
        for bot in ("naive", "careful"):
            with self.subTest(bot=bot):
                recording = self.temp / f"{bot}.jsonl"
                output = self.temp / "replayed.jsonl"
                self.assertEqual(main([*self.run_args, "--bot", bot, "--out", str(recording)]), 0)
                model = FakeModel(bot)
                self.assertEqual([model.answer(case, passages) for case in cases], read_jsonl(recording))
                self.assertEqual(main([
                    *self.run_args, "--bot", "replay", "--recording", str(recording), "--out", str(output),
                ]), 0)
                self.assertEqual(output.read_bytes(), recording.read_bytes())

    def test_replay_preserves_recorded_retrieval(self):
        recording = self.temp / "recording.jsonl"
        output = self.temp / "replayed.jsonl"
        rows = read_jsonl(ANSWERS)
        rows[-1]["retrieved"] = ["returns#1"]
        recording.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        self.assertEqual(main([
            *self.run_args, "--bot", "replay", "--recording", str(recording), "--out", str(output),
        ]), 0)
        self.assertEqual(read_jsonl(output), list(reversed(rows)))

    def test_replay_cli_reports_missing_case_and_writes_no_output(self):
        recording = self.temp / "empty.jsonl"
        recording.write_text("", encoding="utf-8")
        output = self.temp / "replayed.jsonl"
        errors = io.StringIO()
        with redirect_stderr(errors):
            result = main([
                *self.run_args, "--bot", "replay", "--recording", str(recording), "--out", str(output),
            ])
        self.assertEqual(result, 2)
        self.assertIn(f"回放记录缺少用例 {read_jsonl(CASES)[0]['id']} 的回答", errors.getvalue())
        self.assertFalse(output.exists())

    def test_replay_cli_requires_recording(self):
        errors = io.StringIO()
        with redirect_stderr(errors):
            result = main([*self.run_args, "--bot", "replay", "--out", str(self.temp / "out.jsonl")])
        self.assertEqual(result, 2)
        self.assertIn("使用 replay 需要指定 --recording FILE", errors.getvalue())


class HttpChatModelTests(unittest.TestCase):
    ENV = {
        "OPENAI_BASE_URL": "https://example.test/v1/",
        "OPENAI_MODEL": "test-model",
        "OPENAI_API_KEY": "fake-key",
    }
    CASE = {"id": "c-test", "question": "可以退货吗？"}

    def setUp(self):
        env = patch.dict(os.environ, self.ENV, clear=True)
        env.start()
        self.addCleanup(env.stop)
        opener = patch("answercheck.models.urlopen", side_effect=AssertionError("不能访问网络"))
        self.urlopen = opener.start()
        self.addCleanup(opener.stop)
        self.passages = load_kb(KB)

    def test_injected_transport_receives_question_and_every_numbered_passage(self):
        transport = Mock(return_value=chat_reply("可以退货 [returns#1]。"))
        model = HttpChatModel(transport=transport)
        model.answer(self.CASE, self.passages)

        transport.assert_called_once()
        request, = transport.call_args.args
        self.assertEqual(request.full_url, "https://example.test/v1/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-key")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "test-model")
        system_message, user_message = body["messages"]
        self.assertEqual(system_message["role"], "system")
        self.assertIn("[doc#n]", system_message["content"])
        self.assertIn("[转人工]", system_message["content"])
        self.assertEqual(user_message["role"], "user")
        self.assertIn(self.CASE["question"], user_message["content"])
        for passage_id, text in self.passages.items():
            self.assertIn(f"[{passage_id}]\n{text}", user_message["content"])

    def test_reply_keeps_valid_citations_and_detects_handoff(self):
        text = "请参考退货政策 [returns#1] 和保修政策 [warranty#1]。我为你转人工。"
        model = HttpChatModel(transport=Mock(return_value=chat_reply(f"{text}\n[转人工]")))
        self.assertEqual(model.answer(self.CASE, self.passages), {
            "case_id": "c-test", "answer": text, "citations": ["returns#1", "warranty#1"], "handoff": True,
        })

    def test_invented_citation_is_hidden_from_answer_but_fails_report(self):
        case = next(row for row in read_jsonl(DATA / "cases.jsonl") if row["id"] == "c01")
        passages = load_kb(DATA / "kb")
        policy = json.loads((DATA / "policy.json").read_text(encoding="utf-8"))
        text = "签收次日起 7 天内可以申请无理由退货 [returns#1]"
        transport = Mock(return_value=chat_reply(f"{text}。"))
        model = HttpChatModel(transport=transport)

        answer = model.answer(case, passages)
        verdict, = build_report("http", [case], [answer], passages, policy)["cases"]
        self.assertEqual(verdict["verdict"], "pass")

        transport.return_value = chat_reply(f"{text}[returns#999]。")
        with self.assertLogs("answercheck.models", level="WARNING") as logs:
            answer = model.answer(case, passages)
        self.assertEqual(answer["answer"], f"{text}。")
        self.assertIn("BAD_CITATION 用例 c01 引用了不存在的段落 'returns#999'", logs.output[0])
        verdict, = build_report("http", [case], [answer], passages, policy)["cases"]
        self.assertEqual(verdict["verdict"], "fail")
        self.assertEqual(verdict["reasons"], [
            {"label": "BAD_CITATION", "detail": "引用段落「returns#999」不存在"},
        ])
        self.assertEqual(answer["citations"], ["returns#1", "returns#999"])

    def test_reply_without_citations_still_returns_an_answer(self):
        text = "请说明退货原因。"
        model = HttpChatModel(transport=Mock(return_value=chat_reply(text)))
        self.assertEqual(model.answer(self.CASE, self.passages), {
            "case_id": "c-test", "answer": text, "citations": [], "handoff": False,
        })

    def test_reply_denying_handoff_fails_the_required_handoff_check(self):
        case = {
            "id": "c15",
            "question": "我买的冰柜这两天要遇上停电，关着门大概还能保冷几个小时？能帮忙确认一下吗？",
            "expect": {"facts": [], "must_not_include": [], "needs_handoff": True},
        }
        policy = {"forbidden_promises": [], "privacy_patterns": []}
        for text in ("这个问题无需转人工。", "这个问题无需[转人工]。"):
            with self.subTest(text=text):
                model = HttpChatModel(transport=Mock(return_value=chat_reply(text)))
                answer = model.answer(case, self.passages)
                verdict, = build_report("http", [case], [answer], self.passages, policy)["cases"]
                self.assertEqual([reason["label"] for reason in verdict["reasons"]], ["MISSED_HANDOFF"])
                self.assertEqual(verdict["verdict"], "fail")
                self.assertFalse(answer["handoff"])

    def test_cli_hides_credentials_from_transport_error(self):
        key = self.ENV["OPENAI_API_KEY"]
        self.urlopen.side_effect = ValueError(f"Invalid header value b'Bearer {key}'")
        errors = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(errors):
            output = Path(directory) / "out.jsonl"
            result = main([
                "run-bot", "--bot", "http", "--kb", str(KB), "--cases", str(CASES), "--out", str(output),
            ])
            self.assertFalse(output.exists())
        case_id = read_jsonl(CASES)[0]["id"]
        self.assertEqual(result, 2)
        self.assertFalse(key in errors.getvalue(), "HTTP 错误向终端泄露了密钥")
        self.assertIn(f"用例 {case_id} 的模型请求失败", errors.getvalue())

    def test_cli_rejects_echoed_credentials_before_output_or_warning(self):
        key = self.ENV["OPENAI_API_KEY"]
        self.urlopen.side_effect = None
        self.urlopen.return_value.__enter__.return_value.read.return_value = chat_reply(
            f"回复中的密钥为 {key}。[{key}#999]"
        )
        errors = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(errors):
            output = Path(directory) / "out.jsonl"
            with patch("answercheck.models._LOGGER.warning") as warning:
                result = main([
                    "run-bot", "--bot", "http", "--kb", str(KB), "--cases", str(CASES), "--out", str(output),
                ])
            with self.subTest(channel="output"):
                self.assertFalse(output.exists(), "含密钥的回复写入了输出文件")
            with self.subTest(channel="log"):
                self.assertFalse(warning.called, "含密钥的引用触发了日志")
        case_id = read_jsonl(CASES)[0]["id"]
        self.assertEqual(result, 2)
        self.assertNotIn(key, errors.getvalue())
        self.assertIn(f"用例 {case_id} 的模型回复包含 API 密钥", errors.getvalue())

    def test_cli_rejects_truncated_chat_reply(self):
        cases_by_id = {row["id"]: row for row in read_jsonl(DATA / "cases.jsonl")}
        complete = "签收次日起 7 天内可申请无理由退货 [returns#1]。"
        warranty = "整机保修一年 [warranty#1]。"
        self.urlopen.side_effect = None
        response = self.urlopen.return_value.__enter__.return_value
        with tempfile.TemporaryDirectory() as directory:
            cases = Path(directory) / "cases.jsonl"
            cases.write_text(
                "".join(json.dumps(cases_by_id[case_id], ensure_ascii=False) + "\n" for case_id in ("c02", "c01")),
                encoding="utf-8",
            )
            for finish_reason, c01_answer, expected in (
                ("length", complete + "但已", 2),
                ("stop", complete, 0),
            ):
                with self.subTest(finish_reason=finish_reason):
                    response.read.side_effect = [
                        json.dumps({"choices": [{
                            "finish_reason": reason, "message": {"content": content},
                        }]}).encode("utf-8")
                        for reason, content in (("stop", warranty), (finish_reason, c01_answer))
                    ]
                    output = Path(directory) / f"{finish_reason}.jsonl"
                    errors = io.StringIO()
                    with redirect_stderr(errors):
                        result = main([
                            "run-bot", "--bot", "http", "--kb", str(DATA / "kb"), "--cases", str(cases),
                            "--out", str(output),
                        ])
                    self.assertEqual(result, expected, errors.getvalue() or f"结束原因为 {finish_reason}")
                    if finish_reason == "length":
                        self.assertIn("用例 c01 的模型回答被截断", errors.getvalue())
                        self.assertFalse(output.exists(), "同批已有回答被提前写出")
                    else:
                        self.assertEqual(read_jsonl(output), [
                            {"case_id": "c02", "answer": warranty, "citations": ["warranty#1"], "handoff": False},
                            {"case_id": "c01", "answer": complete, "citations": ["returns#1"], "handoff": False},
                        ])

    def test_garbage_reply_reports_case_and_parse_failure(self):
        for body in (b"garbage", b'{"choices": []}', chat_reply(None), chat_reply("  "), chat_reply("???")):
            with self.subTest(body=body):
                model = HttpChatModel(transport=Mock(return_value=body))
                with self.assertRaisesRegex(ValueError, "用例 c-test 的模型回复无法解析"):
                    model.answer(self.CASE, self.passages)

    def test_constructor_rejects_unset_environment(self):
        transport = Mock()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_API_KEY"):
                HttpChatModel(transport=transport)
        transport.assert_not_called()

    def test_cli_refuses_each_missing_environment_variable(self):
        for missing in self.ENV:
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "out.jsonl"
                errors = io.StringIO()
                with patch.dict(os.environ), redirect_stderr(errors):
                    del os.environ[missing]
                    result = main([
                        "run-bot", "--bot", "http", "--kb", str(KB), "--cases", str(CASES), "--out", str(output),
                    ])
                self.assertEqual(result, 2, errors.getvalue())
                self.assertIn(f"使用 http 需要设置环境变量：{missing}", errors.getvalue())
                self.assertFalse(output.exists())
