# Embedded Lookup

[English](./README.en.md)

这个 skill 用于本地嵌入式手册/数据手册/参考手册查证。它当前是一个本地、证据优先的手册检索 skill / CLI，适合回答寄存器、引脚映射、电气参数等问题；不面向远程检索、通用 OCR、原理图或网表解析。

## 当前能力范围

- 面向本地技术文档查证，重点是 datasheet、reference manual，以及其他可提取文本的嵌入式手册。
- 输出形态以 grounded short answer 为主，并附带 key evidence、source details、open questions / uncertainty。
- 对稳定的正向命中，当前已经落地的结构化输出为：
  - `structured_summary.kind = "register"`
  - `structured_summary.kind = "electrical_parameter"`
  - `structured_summary.kind = "pin"`
- 当前稳定的 pin 正向路径是 reference manual 的 `Table 54` 车道。固定回归里，`USART1_TX` / `USART1_RX` 在这条路径上属于 baseline-blocking。
- datasheet 里的 package wording probes（例如 `LQFP48 package`）当前在固定回归中归类为 `extended-conservative`。它们的职责是确认结果保持保守，不漂移成 parameter-style answer；它们不是默认 blocking baseline。

## 当前支持的输入类型

- 单个本地文件路径
- 本地文件夹路径（会递归发现受支持的文档）
- 单独一个问题，此时 CLI 会优先尝试默认本地目录，例如 `手册参考/` 或 `manuals/`
- 支持的文档后缀：
  - `.txt`
  - `.md`
  - `.rst`
  - `.pdf`
- PDF 目前只支持可提取文本的 PDF；OCR 很重的 PDF 不在当前范围内。
- 可选过滤参数：
  - `--device`
  - `--document-type`
  - `--revision`

## 当前 guardrail / conservative fallback

- 当文件夹查询命中多个 plausible manuals，且无法安全收敛到唯一答案时，运行时会停止生成最终结论，并要求补充缩小范围的信息。
- 当多个候选来源之间存在冲突时，运行时会展示 candidate evidence，而不是伪造一个单一确定答案。
- 当问题具有 pin intent，但证据还不足以支持稳定 pin mapping 时，运行时会阻止它退化成 electrical-parameter 风格答案。
- 对上述保守回退路径，当前约束是“不误导、不伪装成 confident structured hit”，而不是“强行给出尽量像答案的句子”。

## 当前已验证的稳定点

- `register`：参考手册正向路径已固定回归，例如 `Which register enables SPI DMA?`
- `electrical_parameter`：数据手册正向路径已固定回归，例如 `VDD operating voltage range`
- `pin`：当前稳定正向路径是 reference manual `Table 54`，而不是 datasheet package wording

这意味着 README 不应把当前能力表述成“全面支持所有芯片、所有 pin 场景”。目前更准确的说法是：寄存器、电气参数，以及一条已验证的 RM `Table 54` pin 正向路径已经落地；更广泛的 pin/package 场景仍保持保守处理。

## 安装

### 技能安装

```bash
npx skills add yinan-yinan/embedded-manual-lookup
```

如果只想安装这个技能，也可以显式指定：

```bash
npx skills add yinan-yinan/embedded-manual-lookup --skill embedded-lookup
```

### 运行依赖

- Python 3.10+
- 可选依赖：`pypdf`（用于解析 PDF）

如果需要支持 PDF：

```bash
python -m pip install pypdf
```

在部分 Windows 环境中，也可以使用：

```bash
py -m pip install pypdf
```

如果你只查询 `.txt`、`.md` 或 `.rst` 手册，则不需要额外依赖。

## 使用方式

安装后，可以直接让 Claude / Codex 帮你查本地手册，例如：

- “查一下这个 PDF 里的 VDD 工作电压范围”
- “哪个寄存器位用来使能 SPI DMA？”
- “Table 54 里 USART1_TX 对应哪个引脚？”

如果你想独立运行 CLI，也可以直接使用：

```bash
python ./scripts/embedded_lookup.py --help
```

基础用法：

```bash
python ./scripts/embedded_lookup.py <手册路径或问题> [问题] [--device <器件>] [--document-type <类型>] [--revision <版本>] [--json]
```

示例：

```bash
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "哪个寄存器位用来使能 SPI DMA？"
```

```bash
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "STM32F103x8B 的 VDD 工作电压范围是多少？" --device STM32F103x8B --document-type datasheet --json
```

```bash
python ./scripts/embedded_lookup.py "E:/path/to/reference-manual.pdf" "Which pin provides USART1_TX on STM32F103x8B in Table 54?" --device STM32F103x8B --document-type "reference manual" --json
```

## 固定回归入口

当前固定回归入口是：

```bash
python ./.trellis/scripts/embedded_lookup_fixed_regression.py
```

默认只跑 `baseline-blocking`。如果需要把 datasheet package probes 一起带上，可以显式启用 extended tier：

```bash
python ./.trellis/scripts/embedded_lookup_fixed_regression.py --include-extended
```

默认 blocking baseline 当前包括：

- CLI / help smoke
- register positive
- electrical positive
- ambiguity blocker
- conflict blocker
- RM `Table 54` `USART1_TX` positive
- RM `Table 54` `USART1_RX` positive

`extended-conservative` 当前用于 datasheet `LQFP48 package` 这类 probe，只做保守性检查，不改变默认 blocking verdict。

## 工作流程

1. 从本地手册或文件夹中筛选候选文档。
2. 按问题检索最相关的章节与片段。
3. 生成 grounded short answer，并附带证据与来源。
4. 如果证据不足、存在冲突，或 pin mapping 不稳定，则进入 conservative fallback。

## 文件结构

```text
embedded-manual-lookup/
├── SKILL.md
├── README.md
├── README.en.md
├── references/
│   └── usage.md
├── scripts/
│   └── embedded_lookup.py
└── spec/
    ├── PRD.md
    └── tasks/
        └── structured-lookup-template/
            ├── PRD.md
            └── spec.md
```

`spec/` 层用于记录这个 skill 的需求、任务拆解和维护规格，不是运行时必需目录，但它定义了能力边界、验证口径和后续演进依据。

## 说明

- 这是本地 manual lookup skill，不联网，也不依赖远程检索服务。
- 当前范围不包括 OCR-heavy PDF、原理图、网表、BOM、截图理解、远程抓取或 retrieval backend 工作。
- 回答策略是 citation-first；在没有足够证据时，优先明确不确定性，而不是补全推测。
