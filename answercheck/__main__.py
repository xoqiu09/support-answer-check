"""Command-line interface for the five answercheck operations."""

import argparse
import json
import sys
from pathlib import Path

from .bots import run_bot
from .checks import validate_data
from .kb import load_kb, load_synonyms
from .report import agreement, build_report, compare_reports


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path):
    rows = []
    with path.open(encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"{path} 第 {number} 行无法读取为 JSON") from error
    return rows


def _write_json(value, path):
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path is None:
        print(text, end="")
    else:
        path.write_text(text, encoding="utf-8")


def _validate(args):
    passages = load_kb(args.kb)
    cases = _read_jsonl(args.cases)
    answers = _read_jsonl(args.answers) if args.answers is not None else None
    errors = validate_data(passages, cases, answers)
    if errors:
        print(*errors, sep="\n", file=sys.stderr)
        return 2
    print("数据检查通过")
    return 0


def _check(args):
    passages = load_kb(args.kb)
    cases = _read_jsonl(args.cases)
    answers = _read_jsonl(args.answers)
    policy = _read_json(args.policy)
    bot = args.answers.name.removesuffix(".jsonl")
    synonyms = load_synonyms(args.kb)
    _write_json(build_report(bot, cases, answers, passages, policy, synonyms), args.out)
    return 0


def _agree(args):
    _write_json(agreement(_read_json(args.report), _read_jsonl(args.labels)), args.out)
    return 0


def _compare(args):
    regressions, fixes = compare_reports(_read_json(args.base), _read_json(args.new))
    print("退步（通过变为不通过）", *(regressions or ["无"]), sep="\n")
    print("修好（不通过变为通过）", *(fixes or ["无"]), sep="\n")
    return 1 if regressions else 0


def _run_bot(args):
    answers = run_bot(args.bot, _read_jsonl(args.cases), load_kb(args.kb))
    text = "".join(json.dumps(answer, ensure_ascii=False) + "\n" for answer in answers)
    args.out.write_text(text, encoding="utf-8")
    return 0


def _add_case_inputs(command):
    command.add_argument("--kb", required=True, type=Path)
    command.add_argument("--cases", required=True, type=Path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="青柚家电客服回答质检")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="检查用例和回答数据")
    _add_case_inputs(validate)
    validate.add_argument("--answers", type=Path)
    validate.set_defaults(run=_validate)

    check = commands.add_parser("check", help="按规则检查回答")
    _add_case_inputs(check)
    check.add_argument("--policy", required=True, type=Path)
    check.add_argument("--answers", required=True, type=Path)
    check.add_argument("--out", required=True, type=Path)
    check.set_defaults(run=_check)

    agree = commands.add_parser("agree", help="比较质检和独立标注")
    agree.add_argument("--report", required=True, type=Path)
    agree.add_argument("--labels", required=True, type=Path)
    agree.add_argument("--out", type=Path)
    agree.set_defaults(run=_agree)

    compare = commands.add_parser("compare", help="找出退步和修好的用例")
    compare.add_argument("--base", required=True, type=Path)
    compare.add_argument("--new", required=True, type=Path)
    compare.set_defaults(run=_compare)

    generate = commands.add_parser("run-bot", help="用假机器人生成回答")
    generate.add_argument("--bot", required=True, choices=("naive", "careful"))
    _add_case_inputs(generate)
    generate.add_argument("--out", required=True, type=Path)
    generate.set_defaults(run=_run_bot)

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except (OSError, ValueError, KeyError) as error:
        print(f"数据处理失败。{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
