"""Summarize checks, compare revisions, and measure label agreement."""

from .checks import CITATION_NOT_RETRIEVED, REASON_LABELS, check_answer, index_answers


def build_report(bot, cases, answers, passages, policy, synonyms=None):
    answers_by_id, errors = index_answers(answers)
    if errors:
        raise ValueError("\n".join(errors))
    by_reason = dict.fromkeys(REASON_LABELS, 0)
    verdicts = []
    failures = 0
    for case in cases:
        case_id = case["id"]
        reasons = check_answer(case, answers_by_id[case_id], passages, policy, synonyms)
        verdict = "fail" if reasons else "pass"
        failures += bool(reasons)
        for reason in reasons:
            label = reason["label"]
            by_reason[label] = by_reason.get(label, 0) + 1
        verdicts.append({"case_id": case_id, "verdict": verdict, "reasons": reasons})
    return {
        "bot": bot,
        "summary": {
            "total": len(verdicts),
            "pass": len(verdicts) - failures,
            "fail": failures,
            "by_reason": by_reason,
        },
        "cases": verdicts,
    }


def _ratio(numerator, denominator):
    return round(numerator / denominator, 3) if denominator else None


def agreement(report, labels):
    labels_by_id = {}
    for row in labels:
        case_id = row["case_id"]
        if case_id in labels_by_id:
            raise ValueError(f"{case_id} 标注重复")
        if row["verdict"] == "pass" and row["reasons"]:
            raise ValueError(f"用例 {case_id} 的通过标注不能包含错误原因")
        labels_by_id[case_id] = row

    report_ids = {case["case_id"] for case in report["cases"]}
    differences = [
        f"{name}缺少 {'、'.join(sorted(missing))}"
        for name, missing in (("报告", labels_by_id.keys() - report_ids),
                              ("标注", report_ids - labels_by_id.keys()))
        if missing
    ]
    if differences:
        raise ValueError("。".join(differences))

    confusion = dict.fromkeys(("both_fail", "checker_only_fail", "labels_only_fail", "both_pass"), 0)
    confusion_keys = {
        ("fail", "fail"): "both_fail",
        ("fail", "pass"): "checker_only_fail",
        ("pass", "fail"): "labels_only_fail",
        ("pass", "pass"): "both_pass",
    }
    per_reason = {label: {"both": 0, "checker_only": 0, "labels_only": 0}
                  for label in REASON_LABELS}
    disagreements = []
    for checker in report["cases"]:
        case_id = checker["case_id"]
        label = labels_by_id[case_id]
        checker_verdict = checker["verdict"]
        labels_verdict = label["verdict"]
        confusion[confusion_keys[checker_verdict, labels_verdict]] += 1

        checker_reasons = [reason["label"] for reason in checker["reasons"]]
        labels_reasons = label["reasons"]
        checker_set, labels_set = set(checker_reasons), set(labels_reasons)
        if CITATION_NOT_RETRIEVED in checker_set or CITATION_NOT_RETRIEVED in labels_set:
            per_reason.setdefault(CITATION_NOT_RETRIEVED, {"both": 0, "checker_only": 0, "labels_only": 0})
        for reason in checker_set & labels_set:
            per_reason[reason]["both"] += 1
        for reason in checker_set - labels_set:
            per_reason[reason]["checker_only"] += 1
        for reason in labels_set - checker_set:
            per_reason[reason]["labels_only"] += 1

        if checker_verdict != labels_verdict:
            disagreements.append({
                "case_id": case_id,
                "checker_verdict": checker_verdict,
                "labels_verdict": labels_verdict,
                "checker_reasons": checker_reasons,
                "labels_reasons": labels_reasons,
            })

    both_fail = confusion["both_fail"]
    return {
        "confusion": confusion,
        "precision": _ratio(both_fail, both_fail + confusion["checker_only_fail"]),
        "recall": _ratio(both_fail, both_fail + confusion["labels_only_fail"]),
        "per_reason": per_reason,
        "disagreements": disagreements,
    }


def compare_reports(base, new):
    for side, report in (("原版", base), ("新版", new)):
        for case in report["cases"]:
            verdict = case["verdict"]
            if verdict not in ("pass", "fail"):
                raise ValueError(f"{side}用例 {case['case_id']} 的判定值无效 {verdict!r}")

    new_verdicts = {case["case_id"]: case["verdict"] for case in new["cases"]}
    base_ids = {case["case_id"] for case in base["cases"]}
    differences = [
        f"{name}缺少 {'、'.join(sorted(missing))}"
        for name, missing in (("新版", base_ids - new_verdicts.keys()),
                              ("原版", new_verdicts.keys() - base_ids))
        if missing
    ]
    if differences:
        raise ValueError("。".join(differences))

    regressions = []
    fixes = []
    for case in base["cases"]:
        case_id = case["case_id"]
        transition = case["verdict"], new_verdicts.get(case_id)
        if transition == ("pass", "fail"):
            regressions.append(case_id)
        elif transition == ("fail", "pass"):
            fixes.append(case_id)
    return regressions, fixes
