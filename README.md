# Embedded Lookup

[English](./README.en.md)

一个面向嵌入式开发的轻量级本地手册检索技能，适合在 Claude Code ,codex 中按需检索本地数据手册、参考手册和其他技术文档喵～

## 功能特点

- 支持本地文件或文件夹检索
- 支持文本文件和文本型 PDF
- 支持按器件、文档类型、版本进行可选过滤
- 返回基于证据的简短答案
- 支持 `--json` 输出，便于脚本集成
- 保留独立 Python CLI 用法，不依赖远程服务

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

安装后，可以直接让 Claude 帮你查本地手册，例如：

- “查一下这个 PDF 里的 VDD 工作电压范围”
- “哪个寄存器位用来使能 SPI DMA？”
- “看看这块板子的 I2C 引脚有哪些”

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
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "这块板子上的 I2C 引脚有哪些？" --json
```

## 工作流程

1. 从本地手册或文件夹中筛选候选文档
2. 按问题检索最相关的章节与片段
3. 提取证据并生成简短回答
4. 在证据不足、冲突或歧义时明确标注不确定性

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

## 兼容性

- 适合支持 `npx skills add` 的技能安装流程
- 也保留本地 Python CLI 直接运行方式
- 当前范围仅限本地文本/PDF 手册检索

## 说明

- 支持的输入是本地文本文件和文本型 PDF。
- 这个工具适用于手册检索。
- OCR 很重的 PDF、原理图、网表和远程抓取不在当前范围内。
