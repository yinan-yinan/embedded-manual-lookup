# Embedded Lookup

一个面向嵌入式开发的轻量级本地手册检索工具。

它可以从本地数据手册、参考手册以及其他技术文本 / PDF 文件中提取证据，并给出带引用的回答，而不需要把整本手册都塞进上下文里。

## 仓库包含内容

这个仓库保持最小上传范围，只包含：

- `README.md`
- `README.zh-CN.md`
- `scripts/embedded_lookup.py`
- `.claude-plugin/plugin.json`
- `skills/embedded-lookup/SKILL.md`

## 功能

- 支持搜索本地文件或文件夹
- 支持文本文件和文本型 PDF
- 支持按器件、文档类型、版本进行可选过滤
- 返回基于证据的简短答案
- 支持 `--json` 输出，便于脚本集成

## 安装

### 环境要求

- Python 3.10+
- 可选依赖：`pypdf`（用于解析 PDF）

### 安装可选 PDF 依赖

如果需要支持 PDF：

```bash
python -m pip install pypdf
```

在部分 Windows 环境中，也可以使用：

```bash
py -m pip install pypdf
```

如果你只查询 `.txt`、`.md` 或 `.rst` 手册，则不需要额外依赖。

## 验证安装

```bash
python ./scripts/embedded_lookup.py --help
```

如果能够正常输出帮助信息，说明 CLI 已可使用。

## CLI 用法

### 基本用法

```bash
python ./scripts/embedded_lookup.py <手册路径或问题> [问题] [--device <器件>] [--document-type <类型>] [--revision <版本>] [--json]
```

### 查询指定手册

```bash
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "这个芯片的 VDD 工作电压范围是多少？"
```

### 带过滤条件查询

```bash
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "哪个寄存器位用来使能 SPI DMA？" --device STM32F103x8B --document-type "reference manual"
```

### 输出 JSON 结果

```bash
python ./scripts/embedded_lookup.py "E:/path/to/manual.pdf" "这块板子上的 I2C 引脚有哪些？" --json
```

### 使用默认手册目录

如果只传一个位置参数，它会被当作问题，工具会尝试默认本地手册目录。

```bash
python ./scripts/embedded_lookup.py "哪个寄存器位用来使能 SPI DMA？"
```

## Skill 包装结构

仓库中也包含最小 Claude skill / plugin 结构：

- `.claude-plugin/plugin.json`
- `skills/embedded-lookup/SKILL.md`

真正的实现位于 `scripts/embedded_lookup.py`，而 `SKILL.md` 只是一个薄包装层。

## 说明

- 支持的输入是本地文本文件和文本型 PDF。
- 这个工具只用于手册检索。
- OCR 很重的 PDF、原理图、网表和远程抓取不在当前范围内。
