"""Answer adapters for deterministic bots, recordings, and chat completions."""

import json
import logging
import os
import re
from pathlib import Path
from typing import Mapping, Protocol, TypedDict
from urllib.request import Request, urlopen

from .bots import run_bot


class Answer(TypedDict):
    case_id: str
    answer: str
    citations: list[str]
    handoff: bool


class Model(Protocol):
    def answer(self, case: dict, passages: Mapping[str, str]) -> Answer:
        ...


class FakeModel:
    def __init__(self, bot):
        self.bot = bot

    def answer(self, case, passages):
        return next(run_bot(self.bot, (case,), passages))


class ReplayModel:
    def __init__(self, recording):
        self._answers = {}
        with Path(recording).open(encoding="utf-8") as source:
            for number, line in enumerate(source, 1):
                location = f"回放文件 {recording} 第 {number} 行"
                try:
                    answer = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"{location}无法读取为 JSON") from error
                if not _is_answer(answer):
                    raise ValueError(f"{location}不符合回答格式")
                case_id = answer["case_id"]
                if case_id in self._answers:
                    raise ValueError(f"{location}的用例 {case_id} 重复")
                self._answers[case_id] = answer

    def answer(self, case, passages):
        case_id = case["id"]
        if case_id not in self._answers:
            raise ValueError(f"回放记录缺少用例 {case_id} 的回答")
        answer = self._answers[case_id]
        return {**answer, "citations": answer["citations"].copy()}


def _is_answer(row):
    return (
        isinstance(row, dict)
        and row.keys() == Answer.__annotations__.keys()
        and isinstance(row["case_id"], str)
        and isinstance(row["answer"], str)
        and isinstance(row["citations"], list)
        and all(isinstance(citation, str) for citation in row["citations"])
        and isinstance(row["handoff"], bool)
    )


_HTTP_ENV = ("OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_API_KEY")
_HANDOFF_MARKER = "[转人工]"
_SYSTEM_PROMPT = (
    "你是青柚家电客服。请根据提供的知识库段落回答顾客问题。"
    "引用段落时，在相关说法后用 [doc#n] 格式标注实际段落编号。"
    "先输出给顾客看的答复。无法根据知识库回答或需要人工处理时，"
    f"请另起一行，以 {_HANDOFF_MARKER} 作为最后一行的全部内容。无需转人工时省略这一行。"
)
_CITATION = re.compile(r"\[([^\[\]\r\n]+#[0-9]+)\]")
_LOGGER = logging.getLogger(__name__)


def _post(request):
    with urlopen(request, timeout=30) as response:
        return response.read()


def _parse_reply(reply, case_id, passages, api_key):
    try:
        content = json.loads(reply)["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise ValueError(f"用例 {case_id} 的模型回复无法解析，缺少有效的聊天回复") from None
    if not isinstance(content, str):
        content = ""
    if api_key in content:
        raise ValueError(f"用例 {case_id} 的模型回复包含 API 密钥，已拒绝")

    content = content.strip()
    body, _, last_line = content.rpartition("\n")
    handoff = last_line.strip() == _HANDOFF_MARKER
    if handoff:
        content = body
    if not any(char.isalnum() for char in _CITATION.sub("", content)):
        raise ValueError(f"用例 {case_id} 的模型回复无法解析，没有可用的答复正文")

    citations = []

    def keep_known_citation(match):
        passage_id = match[1]
        if passage_id not in passages:
            _LOGGER.warning("BAD_CITATION 用例 %s 引用了不存在的段落 %r，已移除", case_id, passage_id)
            return ""
        if passage_id not in citations:
            citations.append(passage_id)
        return match[0]

    answer = _CITATION.sub(keep_known_citation, content).strip()
    return {"case_id": case_id, "answer": answer, "citations": citations, "handoff": handoff}


class HttpChatModel:
    """The transport takes a urllib Request and returns the response body."""

    def __init__(self, transport=_post):
        settings = {name: os.environ.get(name, "").strip() for name in _HTTP_ENV}
        missing = [name for name, value in settings.items() if not value]
        if missing:
            raise ValueError(f"使用 http 需要设置环境变量：{', '.join(missing)}")
        self._url = settings["OPENAI_BASE_URL"].rstrip("/") + "/chat/completions"
        self._model = settings["OPENAI_MODEL"]
        self._key = settings["OPENAI_API_KEY"]
        self._transport = transport

    def answer(self, case, passages):
        numbered = "\n\n".join(f"[{passage_id}]\n{text}" for passage_id, text in passages.items())
        prompt = f"顾客问题：{case['question']}\n\n知识库段落：\n{numbered}"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            request = Request(
                self._url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            request.add_unredirected_header("Authorization", f"Bearer {self._key}")
            reply = self._transport(request)
        except Exception:
            # Request and transport exceptions can contain the authorization header.
            raise ValueError(f"用例 {case['id']} 的模型请求失败") from None
        return _parse_reply(reply, case["id"], passages, self._key)
