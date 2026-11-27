# 青柚家电客服回答质检

客服团队抽查售后答复时，要逐条翻政策才能确认客服有没有讲清退货例外、按要求转人工或作出超出政策的承诺。

- 批量检查答复中的错答、漏答，以及知识库引用是否包含所需依据。
- 标出漏转或多转人工、违规承诺和疑似隐私泄露。
- 对照独立 AI 标注，并列出换版后由通过变为不通过或反过来的用例。

## 怎么验证的

实跑 `/opt/homebrew/bin/python3 -m unittest`，**56 项测试全部通过**。测试确认了漏答已安装商品的退货例外、引用缺少所需依据、该转人工却没转都会被标出，换版后的退步也会被列出。逐项临时关掉事实、引用、转人工、承诺和隐私检查，每次都有对应测试按预期失败。

[打开在线演示](https://xoqiu.cn/answer-check-demo/index.html)

克隆后在仓库根目录运行以下两条命令，先生成示例质检报告，再跑测试。Python 版本要求见[完整运行说明](#怎么跑)。

```sh
python3 -m answercheck check --kb data/kb --cases data/cases.jsonl \
  --policy data/policy.json --answers data/answers/careful.jsonl --out answer-check-report.json
python3 -m unittest
```

项目使用虚构数据，演示和测试未调用真实模型，也没有真实用户参与。我负责定义需求和验收标准，指挥 AI 编程工具实现。

## English overview

Support teams spend time looking up policies when reviewing after-sales replies.\
Support Answer Check flags factual errors and omissions, missing citations or citations that lack the required text, incorrect handoffs, unauthorized promises, and potential privacy leaks.\
It compares two rule-based bots on the same 40 fictional cases, shows which cases improve or regress, and checks the results against independent AI labels.\
All 56 tests passed, and existing tests failed as expected when individual checks were deliberately disabled.\
I set the requirements and acceptance criteria and directed AI coding tools to build it. The demo and tests use fictional data, with no live model calls or real users.

## 怎么跑

在仓库根目录运行。需要 Python 3.10 或更新版本，只用标准库。下面的假客服示例和测试全程离线，使用 `/opt/homebrew/bin/python3`。如果你的 Python 装在别处，可以换成指向相应版本的 `python3`。

先生成两个机器人的回答，再检查用例和回答数据。

```sh
/opt/homebrew/bin/python3 -m answercheck run-bot --bot naive --kb data/kb --cases data/cases.jsonl --out data/answers/naive.jsonl
/opt/homebrew/bin/python3 -m answercheck run-bot --bot careful --kb data/kb --cases data/cases.jsonl --out data/answers/careful.jsonl
/opt/homebrew/bin/python3 -m answercheck validate --kb data/kb --cases data/cases.jsonl --answers data/answers/naive.jsonl
/opt/homebrew/bin/python3 -m answercheck validate --kb data/kb --cases data/cases.jsonl --answers data/answers/careful.jsonl
```

生成质检报告、一致性报告和回归报告。回归报告列出哪些题从通过变为不通过，以及哪些题从不通过变为通过。两份报告的题号一致时，`compare` 无退步返回 0，有退步返回 1。题号不一致时返回 2，并列出缺少的题号。

```sh
/opt/homebrew/bin/python3 -m answercheck check --kb data/kb --cases data/cases.jsonl --policy data/policy.json --answers data/answers/naive.jsonl --out reports/naive.json
/opt/homebrew/bin/python3 -m answercheck check --kb data/kb --cases data/cases.jsonl --policy data/policy.json --answers data/answers/careful.jsonl --out reports/careful.json
/opt/homebrew/bin/python3 -m answercheck agree --report reports/naive.json --labels data/labels/naive.jsonl --out reports/agree-naive.json
/opt/homebrew/bin/python3 -m answercheck agree --report reports/careful.json --labels data/labels/careful.jsonl --out reports/agree-careful.json
/opt/homebrew/bin/python3 -m answercheck compare --base reports/naive.json --new reports/careful.json > reports/compare.txt
```

运行单元测试。

```sh
/opt/homebrew/bin/python3 -m unittest -v
```

可以用 `--bot replay` 离线回放已有回答，也可以用 `--bot http` 调用配置好的模型服务。[模型接入与回放说明](docs/M2.md)

## 两个假客服的结果

- naive 共 40 题，10 题通过，30 题不通过。事实错误 22 次，规则判引用有误 11 次，漏转人工 14 次，乱承诺 1 次。[naive 质检报告](reports/naive.json)
- careful 共 40 题，23 题通过，17 题不通过。事实错误 5 次，规则判引用有误 5 次，漏转人工 13 次，乱承诺 0 次。[careful 质检报告](reports/careful.json)
- 两个机器人的缺少引用、多余转人工和隐私泄露计数各为 0。同一题可以有多个不通过原因。
- 从 naive 换到 careful，有 13 题从不通过变为通过，0 题退步。[回归报告](reports/compare.txt)

## 规则质检与独立标注

初版独立标注由一名没有读过质检代码的 AI 标注员完成。它逐条阅读用例、知识库和回答，Claude 抽查了其中 10 条（naive 和 careful 各 5 题），判断与知识库一致。naive 的第 36、38 题更新后，由另一名 AI 标注员独立复标。该标注员只看了这两题的用例、回答、所引知识库段落和标注规则。

- naive 的 40 题里，双方都判不通过 30 题，都判通过 10 题。仅质检判不通过和仅标注判不通过都为 0。精确率为 1.0，召回率为 1.0。[naive 一致性报告](reports/agree-naive.json)
- careful 的 40 题里，双方都判不通过 17 题，都判通过 23 题。仅质检判不通过和仅标注判不通过都为 0。精确率为 1.0，召回率为 1.0。[careful 一致性报告](reports/agree-careful.json)

这里的精确率是质检判不通过的题里，标注也判不通过的比例。召回率是标注判不通过的题里，质检也判不通过的比例。两个数都只描述这组虚构用例的判定。

careful 的原因标签全部一致。naive 的原因差异从三道题减到一道，40 道题的通过判定维持原样。事实匹配会统一常见数字及单位写法，并使用知识库里列出的同义词。例如，「通过身份验证」也能匹配「核验身份」，c33 和 c40 现在只报告漏转人工。[同义词表](data/kb/synonyms.json)

c26 问已安装的洗衣机能否无理由退货。双方都指出回答漏了已安装商品的例外。引用段落写着「商品须未安装」，读者能从中找到相关依据。规则额外判引用有误，因为该段没有逐字包含用例指定的证据「定制商品和已安装的商品不适用无理由退货」。

## 留出集

Codex 根据知识库手写了 12 道新题和两套固定回答。两套回答共用一份预先写好的标签，各有 6 条正确转述和 6 条改错事实的回答。用旧版检查器跑完后，保留同一批数据来测新版。新版试跑发现数字前的空格也会造成漏判，修正后进行了复跑。[用例](data/heldout/cases.jsonl) · [标签](data/heldout/labels.jsonl)

旧版的判定与标签一致 10/24 条（naive 4/12，careful 6/12）。用这批题发现并修正数字前的空格问题后，同批复跑一致 24/24 条。两套回答各通过 6 条，另 6 条都判事实错误。独立盲测需要在规则定稿后首次评测新题。可以用现有 `check` 和 `agree` 命令复跑，将用例、回答和标签路径改为 `data/heldout/` 下的对应文件。[修改前报告](reports/heldout-before.json) · [修改后报告](reports/heldout-after.json)

## 还没做

- 判断词表之外的同义表达，以及不同表述的证据是否支持回答。
