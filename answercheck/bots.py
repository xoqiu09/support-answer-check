"""Deterministic stand-ins for customer service bots."""

import re


MIN_OVERLAP = 1
HANDOFF_WORDS = ("投诉", "律师", "媒体", "人工", "赔偿争议")
_SENTENCE_END = re.compile(r"[。！？!?]+|(?<!\d)\.|\.(?!\d)")
_INJECTION = re.compile(
    r"(?:忽略[^，。！？\n]{0,16}规则|你(?:现在)?是管理员|按[^，。！？\n]{0,16}规则答).*?"
    r"(?:回答|回复|输出|说|答(?=\s*[:：])|照抄(?:这一句|这句话)?)"
    r"(?:以下内容)?\s*[:：]?\s*(?P<reply>[^\n]+)",
    re.DOTALL,
)
_QUOTED_REPLY = re.compile(r"「[^」]+」|『[^』]+』|“[^”]+”")
# Match complete numbers before treating spaces as part of a number.
_NUMBER = re.compile(r"(?<!\d)(?:\d(?:-?\d){7,}|(?:\d[ -]?){7,}\d)(?!\d)")
_PHONE_NUMBER = re.compile(r"(?<!\d)1(?:[ -]?\d){10}(?!\d)")


def _bigrams(text):
    runs = re.findall(r"[^\W_]+", text.casefold())
    return {run[index:index + 2] for run in runs for index in range(len(run) - 1)}


def _first_sentence(text):
    end = _SENTENCE_END.search(text)
    return text[:end.end()] if end else text


def _digits(text):
    return text.replace(" ", "").replace("-", "")


def _omit_user_numbers(text, question):
    # A general number match can span multiple space-separated phone numbers.
    user_numbers = {
        _digits(number)
        for pattern in (_NUMBER, _PHONE_NUMBER)
        for number in pattern.findall(question)
    }

    def omit(match):
        number = match[0]
        return "（号码已省略）" if _digits(number) in user_numbers else number

    return _PHONE_NUMBER.sub(omit, _NUMBER.sub(omit, text))


def _naive(question, ranked, passages):
    passage_id = ranked[0]
    text = _first_sentence(passages[passage_id])
    injection = _INJECTION.search(question)
    if injection:
        text = injection["reply"].strip()
        quoted = _QUOTED_REPLY.match(text)
        if quoted:
            text = quoted[0][1:-1]
    return text, [passage_id], False


def _careful(question, ranked, passages, highest_overlap):
    if highest_overlap < MIN_OVERLAP:
        return "知识库没有找到相关说明，我为你转人工核实。", [], True

    citations = ranked[:2]
    text = "\n".join(passages[passage_id] for passage_id in citations)
    handoff = any(word in question for word in HANDOFF_WORDS)
    if handoff:
        text += "\n这件事需要人工处理，我为你转人工。"
    return _omit_user_numbers(text, question), citations, handoff


def run_bot(bot, cases, passages):
    """Yield one deterministic answer row for each case, in input order."""
    if not passages:
        raise ValueError("知识库没有可检索的段落")
    passage_terms = {passage_id: _bigrams(body) for passage_id, body in passages.items()}
    for case in cases:
        question = case["question"]
        terms = _bigrams(question)
        scores = {passage_id: len(terms & words) for passage_id, words in passage_terms.items()}
        # Python's stable sort keeps knowledge-base order for tied scores.
        ranked = sorted(scores, key=scores.get, reverse=True)
        if bot == "naive":
            text, citations, handoff = _naive(question, ranked, passages)
        else:
            text, citations, handoff = _careful(question, ranked, passages, scores[ranked[0]])
        yield {"case_id": case["id"], "answer": text, "citations": citations, "handoff": handoff}
