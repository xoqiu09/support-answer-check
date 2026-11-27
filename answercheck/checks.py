"""Apply the seven quality checks to one case and answer."""

import re

from .facts import contains_fact, normalize_fact_text


# 必须出现的事实前后带明确否定（如「无需核验身份」）时，不算答出了这条事实。
_NEGATION_BEFORE = r"(?:无[须需]|不(?:必|用|须|需要?|会)|可(?:以)?不|免于)\s*(?:(?:先|再|进行|通过|做)\s*)*"
_NEGATION_AFTER = r"\s*(?:不(?:是必需的|需要)|可(?:以)?(?:跳过|省略))"


def _without_negated(text, phrase):
    escaped = re.escape(phrase)
    return re.sub(_NEGATION_BEFORE + escaped + "|" + escaped + _NEGATION_AFTER, " ", text)


REASON_LABELS = (
    "WRONG_FACT",
    "NO_CITATION",
    "BAD_CITATION",
    "MISSED_HANDOFF",
    "NEEDLESS_HANDOFF",
    "OVERPROMISE",
    "PRIVACY_LEAK",
)


def _add_reason(reasons, label, details):
    if details:
        reasons.append({"label": label, "detail": "。".join(details)})


def index_answers(answers):
    answers_by_id = {}
    errors = []
    for answer in answers:
        case_id = answer["case_id"]
        if case_id in answers_by_id:
            errors.append(f"用例 {case_id} 回答重复")
        answers_by_id[case_id] = answer
    return answers_by_id, errors


def validate_data(passages, cases, answers=None):
    """Return errors in case data and, when provided, answer references."""
    errors = []
    case_ids = set()
    for case in cases:
        case_id = case["id"]
        if case_id in case_ids:
            errors.append(f"用例编号重复（{case_id}）")
        case_ids.add(case_id)
        for fact in case["expect"]["facts"]:
            passage_id = fact["passage"]
            if passage_id not in passages:
                errors.append(f"用例 {case_id} 的段落 {passage_id} 不存在")
            elif fact["evidence"] not in passages[passage_id]:
                evidence = fact["evidence"]
                errors.append(f"用例 {case_id} 的段落 {passage_id} 缺少原文「{evidence}」")

    if answers is not None:
        answers = list(answers)
        answers_by_id, duplicate_errors = index_answers(answers)
        errors.extend(duplicate_errors)
        for answer in answers:
            case_id = answer["case_id"]
            if case_id not in case_ids:
                errors.append(f"回答引用的用例 {case_id} 不存在")
            for passage_id in answer["citations"]:
                if passage_id not in passages:
                    errors.append(f"用例 {case_id} 的回答引用了不存在的段落 {passage_id}")
        for case_id in sorted(case_ids - answers_by_id.keys()):
            errors.append(f"用例 {case_id} 缺少回答")
    return errors


def check_answer(case, answer, passages, policy, synonyms=None):
    """Return the reasons for failing, in the specified label order."""
    expect = case["expect"]
    facts = expect["facts"]
    text = answer["answer"]
    citations = answer["citations"]
    reasons = []

    fact_text = normalize_fact_text(text, synonyms)

    def matches(phrase, *, required=False):
        normalized = normalize_fact_text(phrase, synonyms)
        if required:
            return contains_fact(_without_negated(fact_text, normalized), normalized)
        return contains_fact(fact_text, normalized)

    wrong_facts = [f"缺少「{fact['must_include']}」" for fact in facts
                   if not matches(fact["must_include"], required=True)]
    wrong_facts.extend(f"出现禁止内容「{phrase}」" for phrase in expect["must_not_include"]
                       if matches(phrase))
    _add_reason(reasons, "WRONG_FACT", wrong_facts)

    if facts and not citations:
        evidence = "、".join(fact["evidence"] for fact in facts)
        _add_reason(reasons, "NO_CITATION", [f"未引用段落，无法核对「{evidence}」"])
    elif facts:
        valid_texts = [passages[passage_id] for passage_id in citations if passage_id in passages]
        bad_citations = [f"引用段落「{passage_id}」不存在" for passage_id in citations
                         if passage_id not in passages]
        bad_citations.extend(f"引用未包含原文「{fact['evidence']}」" for fact in facts
                             if not any(fact["evidence"] in body for body in valid_texts))
        _add_reason(reasons, "BAD_CITATION", bad_citations)

    if expect["needs_handoff"] and not answer["handoff"]:
        _add_reason(reasons, "MISSED_HANDOFF", ["用例要求转人工，回答未转人工"])
    elif not expect["needs_handoff"] and answer["handoff"]:
        _add_reason(reasons, "NEEDLESS_HANDOFF", ["用例无需转人工，回答却转了人工"])

    promises = [f"出现禁止承诺「{phrase}」" for phrase in policy["forbidden_promises"]
                if phrase in text]
    _add_reason(reasons, "OVERPROMISE", promises)
    privacy = [f"匹配隐私规则「{pattern}」" for pattern in policy["privacy_patterns"]
               if re.search(pattern, text)]
    _add_reason(reasons, "PRIVACY_LEAK", privacy)
    return reasons
