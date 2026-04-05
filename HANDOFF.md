# embedded-manual-lookup 接力文档

更新时间：`2026-04-05`

## 一句话结论

当前真正的续作起点不是重做 retrieval，也不是继续收敛 `constraint-gate`，而是把 2026-04-02 已验证通过的 Phase 2 结果当成新的续作基线。  
Phase 1 已封板；`phase2-feature-ordering` runner 已 PASS；`phase1-table-aware + phase2-feature-ordering` combined run 已 PASS；`phase2-package-stm32f103c8-refusal` 已 PASS；`phase2-flash-stm32f103c8-refusal` 已 PASS；`phase2-ordering-stm32f103c8-refusal` 已 PASS；`04-02-package-ordering-device-variant-sibling-ambiguity-refusal` 已完成；`regression-packaging` 已完成。

## 2026-04-05 PDF backend 最小 A/B 实验

- 本次补记范围：
  - `E:/Aiskillls/embedded-manual-lookup/HANDOFF.md`
- backend 抽象方式：
  - `EmbeddedRetrievalPrototype.__init__()` 新增 `pdf_backend`，默认值保持 `pypdf`。
  - CLI 新增 `--pdf-backend {pypdf,pdfplumber}`；同时支持环境变量 `EMBEDDED_LOOKUP_PDF_BACKEND` 覆盖默认值。
  - `_load_pdf_document()` 现在只负责 dispatch，分别走 `_load_pdf_document_with_pypdf()` 和 `_load_pdf_document_with_pdfplumber()`，输出仍保持 `list[PageText]`，下游 heuristics 未改。
  - 当所选 backend 缺依赖时，单文件和目录模式都会直接抛出清晰错误，不再把“所有 PDF 都加载失败”静默降级成空文档列表。
- `pdfplumber` 接入状态：
  - 事实：代码路径已接好。
  - 事实：当前 Python 环境已安装 `pdfplumber`，本轮已完成真实 focused A/B。
- focused fixture 与命令：
  - fixture：`E:/Aiskillls/embedded-manual-lookup/fixtures/stm32f103-revision-conflict-pd0pd1`
  - `python scripts/embedded_lookup.py "E:/Aiskillls/embedded-manual-lookup/fixtures/stm32f103-revision-conflict-pd0pd1" "For STM32F103x8/xB in the LFBGA100 package, which ball is PD0?" --json`
  - `python scripts/embedded_lookup.py "E:/Aiskillls/embedded-manual-lookup/fixtures/stm32f103-revision-conflict-pd0pd1" "For STM32F103x8/xB in the LFBGA100 package, which ball is PD1?" --json`
  - `python scripts/embedded_lookup.py "E:/Aiskillls/embedded-manual-lookup/fixtures/stm32f103-revision-conflict-pd0pd1" "For STM32F103x8/xB in the LFBGA100 package, which ball is PD0?" --pdf-backend pdfplumber --json`
  - `python scripts/embedded_lookup.py "E:/Aiskillls/embedded-manual-lookup/fixtures/stm32f103-revision-conflict-pd0pd1" "For STM32F103x8/xB in the LFBGA100 package, which ball is PD1?" --pdf-backend pdfplumber --json`
  - `python E:\Aiskillls\.trellis\scripts\embedded_lookup_fixed_regression.py --include-phase2-stm32f103-revision-conflict-rerun`
- A/B 结果：
  - `pypdf` / `PD0`
    - heading 干净度：好；`sources[*].section` 都是 `Table 5. Medium-density STM32F103xx pin definitions`
    - pin 值是否正确：正确；`short_answer` 为 `Different source candidates disagree on the pin mapping for PD0: Rev 17 shows -; Rev 20 shows D8.`
    - caption 是否稳定：稳定；`key_evidence` 同时保留 Rev 17 / Rev 20，且都落在同一 `Table 5` caption
    - Nearby row 是否可读：可读；excerpt 分别为 `Pin definitions table for LFBGA100 shows PD0 as -. Nearby row: - C9 - C1 - 81 2 PD0 I/O FT PD0 - CANRX` 和 `Pin definitions table for LFBGA100 shows PD0 as D8. Nearby row: D8 C9 - C1 - 81 2 PD0 I/O FT PD0 - CANRX`
  - `pypdf` / `PD1`
    - heading 干净度：好；无 `Pc13-Tamper-Rtc` 或异常 glyph 回流
    - pin 值是否正确：正确；`short_answer` 为 `Different source candidates disagree on the pin mapping for PD1: Rev 17 shows -; Rev 20 shows E8.`
    - caption 是否稳定：稳定；`key_evidence` 同时保留 Rev 17 / Rev 20，且都落在同一 `Table 5` caption
    - Nearby row 是否可读：可读；excerpt 分别为 `Pin definitions table for LFBGA100 shows PD1 as -. Nearby row: - B9 - D1 - 82 3 PD1 I/O FT PD1 - CANTX` 和 `Pin definitions table for LFBGA100 shows PD1 as E8. Nearby row: E8 B9 - D1 - 82 3 PD1 I/O FT PD1 - CANTX`
  - `pdfplumber` / `PD0`
    - heading 干净度：差；`sources[0].section` 退化为 `3 > Pinouts and pin description`，没有稳定回到 `Table 5`
    - pin 值是否正确：不满足 focused 目标；`short_answer` 退化为 `One candidate source surfaces a pin mapping, but the other candidate sources do not support a single grounded pin answer yet.`，丢失 Rev 20 `D8`
    - caption 是否稳定：不稳定；`key_evidence` 只剩 `STM32F103X8 rev 17: shows PD0 as - in 3 > Pinouts and pin description (page 21-35).`
    - Nearby row 是否可读：局部可读；仍能抽到 `Pin definitions table for LFBGA100 shows PD0 as -. Nearby row: - C9 - C1 - 81 2 PD0 I/O FT PD0 - CANRX`，但缺少 Rev 20 行
  - `pdfplumber` / `PD1`
    - heading 干净度：差；`sources[0].section` 同样退化为 `3 > Pinouts and pin description`
    - pin 值是否正确：不满足 focused 目标；`short_answer` 同样退化为单源保守回答，丢失 Rev 20 `E8`
    - caption 是否稳定：不稳定；`key_evidence` 只剩 `STM32F103X8 rev 17: shows PD1 as - in 3 > Pinouts and pin description (page 21-35).`
    - Nearby row 是否可读：局部可读；仍能抽到 `Pin definitions table for LFBGA100 shows PD1 as -. Nearby row: - B9 - D1 - 82 3 PD1 I/O FT PD1 - CANTX`，但缺少 Rev 20 行
- focused 结论：
  - 事实：在这组 `PD0` / `PD1` probe 上，`pypdf` 在 4 个指标上都优于 `pdfplumber`；`heading 干净度`、`caption 稳定性`、`pin 值完整性` 三项优势明确，`Nearby row` 两者都能读到 Rev 17 行，但只有 `pypdf` 能稳定保留 Rev 20 行。
  - 事实：`pdfplumber` 当前真实退化不是“轻微排序差异”，而是漏掉第二个 conflict source，导致 conflict summary 无法成立。
- 本次额外验证结果：
  - `python E:\Aiskillls\.trellis\scripts\embedded_lookup_fixed_regression.py --include-phase2-stm32f103-revision-conflict-rerun`
  - 结果：`baseline-blocking` PASS，`phase2-stm32f103-revision-conflict-rerun` PASS，overall selected blocking verdict PASS
- 当前结论：
  - 事实：backend 抽象已经最小接入，默认行为仍是 `pypdf`，且 STM32 revision-conflict 基线未回退。
  - 事实：就当前 focused fixture 而言，没有看到继续扩大 `pdfplumber` 实验的正向信号；若继续扩大，目的应是定位失败模式，而不是评估是否切默认值。
  - 建议：默认值保持 `pypdf`；在修复 `pdfplumber` 对 STM32 revision-conflict 的多源保留前，不建议把它扩到更大 pin fixture 集合做收益验证。
  - 风险：本次只覆盖 `stm32f103-revision-conflict-pd0pd1` 和 `PD0` / `PD1` 两个 probe；它足以说明当前 backend 默认值不该切换，但还不足以概括 `pdfplumber` 在所有 query family 上的整体表现。

## 2026-04-04 第二次窄修复状态

- 本次只改了 `E:/Aiskillls/embedded-manual-lookup/scripts/embedded_lookup.py`。
- 已处理的两个近因：
  - `PD1 -> D1` 残留误取：`_extract_pin_mapping_values()` 对 `ball + 显式 package` 进一步收紧 nearest-left fallback；当 row fragment 丢失请求 package / package-code scope 时，不再允许左侧误取进入候选。
  - Rev 20 `D8/E8` 丢失：conflict fallback 不再只回退到 `evidence[0]`；pin query 会先复用 pin-aware 选择，并在 chunk 级证据不足时回退到 section 级 pin evidence。对 `ball + multi-package table` 额外补了 header-anchored 的局部提取，只在同一窗口内能看到 package header 时才使用。
- 本次执行并确认通过的命令：
  - `python E:\Aiskillls\.trellis\scripts\embedded_lookup_fixed_regression.py --include-phase2-stm32f103-revision-conflict-rerun`
  - `python E:\Aiskillls\.trellis\scripts\embedded_lookup_fixed_regression.py --include-phase2-feature-ordering --include-phase2-stm32f103-revision-conflict-rerun`
- 当前结果：
  - `phase2-stm32f103-revision-conflict-rerun`：PASS
  - `phase2-feature-ordering`：PASS
  - combined blocking verdict：PASS
- 当前剩余风险：
  - Rev 17 的 section 级证据仍带有明显 OCR 噪声，虽然 conflict summary 已能稳定给出 `Rev 17 shows -; Rev 20 shows D8/E8`，但相关 excerpt 可读性仍弱。
  - 新增的 header-anchored ball 提取是局部策略，只应覆盖 `explicit package + ball + multi-package pin table`；若后续扩展 pin 表能力，先复核它在其他 BGA/package 表上的副作用，再决定是否推广。

## 2026-04-04 第三次窄修复状态

- 本次改动范围：
  - `E:/Aiskillls/embedded-manual-lookup/scripts/embedded_lookup.py`
  - `E:/Aiskillls/embedded-manual-lookup/HANDOFF.md`
- 本次目标不是再改 conflict 判定，而是只改善 section-level pin fallback 的 `sources[*].excerpt` 可读性。
- 实际落点：
  - `_best_pin_section_evidence_for_document()` 不再直接把 `_extract_relevant_excerpt(section.text, ...)` 的原始 OCR 片段暴露给 section fallback。
  - 新增局部 helper，仅供 section-level pin fallback 使用：优先生成 `Pin definitions table for <package> shows <pin> as <value>. Nearby row: <row>` 这种短摘要；如果抓不到可用 row，再退回轻量清洗后的原 excerpt。
  - row 选取增加了简单打分，优先选择包含 pin 值、重复 pin token、`I/O` 列和足够列数的真正 pin-definition table row，避免误摘 `PD0-OSC_IN` / `PD1-OSC_OUT` 这类 figure 行。
- 本次直接 fixture 观察结果：
  - `PD0`：`short_answer` 仍是 `Rev 17 shows -; Rev 20 shows D8`；excerpt 变为：
    - Rev 17：`Pin definitions table for LFBGA100 shows PD0 as -. Nearby row: - C9 - C1 - 81 2 PD0 I/O FT PD0 - CANRX`
    - Rev 20：`Pin definitions table for LFBGA100 shows PD0 as D8. Nearby row: D8 C9 - C1 - 81 2 PD0 I/O FT PD0 - CANRX`
  - `PD1`：`short_answer` 仍是 `Rev 17 shows -; Rev 20 shows E8`；excerpt 变为：
    - Rev 17：`Pin definitions table for LFBGA100 shows PD1 as -. Nearby row: - B9 - D1 - 82 3 PD1 I/O FT PD1 - CANTX`
    - Rev 20：`Pin definitions table for LFBGA100 shows PD1 as E8. Nearby row: E8 B9 - D1 - 82 3 PD1 I/O FT PD1 - CANTX`
- 本次执行并确认通过的命令：
  - `python E:\Aiskillls\.trellis\scripts\embedded_lookup_fixed_regression.py --include-phase2-stm32f103-revision-conflict-rerun`
  - `python E:\Aiskillls\.trellis\scripts\embedded_lookup_fixed_regression.py --include-phase2-feature-ordering --include-phase2-stm32f103-revision-conflict-rerun`
- 当前结果：
  - `phase2-stm32f103-revision-conflict-rerun`：PASS
  - `phase2-feature-ordering`：PASS
  - combined blocking verdict：PASS
- 本次后剩余风险：
  - 这次 excerpt 优化是“局部摘要化”而不是通用 OCR 修复；它只覆盖 section-level pin fallback，不会改善其他 query family 的 excerpt 噪声。
  - row 选取目前依赖轻量启发式打分；若后续遇到更复杂的多行 pin row 或异常列布局，可能仍需要再补更细的表格行拼接，但不应直接把这次局部逻辑推广到全局 `_extract_relevant_excerpt()`。

## 2026-04-04 第四次窄修复状态

- 本次改动范围：
  - `E:/Aiskillls/embedded-manual-lookup/scripts/embedded_lookup.py`
  - `E:/Aiskillls/embedded-manual-lookup/HANDOFF.md`
- 本次目标不是改 heading detection，也不是改 conflict 判定；只在 pin conflict 返回层清理 `sources[*].section` 和 `key_evidence` 里的脏 heading。
- 实际落点：
  - `_build_conflict_result()` 在 pin conflict 分支进入后，会先对返回用的 `relevant_evidence` 做局部 `section` 归一化，不改前序检索与判定链路。
  - 仅对可疑 label 生效：单个异常非 ASCII glyph，以及像 `Pc13-Tamper-Rtc` 这类明显来自 pin table 正文/figure 文本的残留 heading。
  - 可疑时优先从当前 evidence 自身的 `full_text` / `excerpt` 回退到稳定 caption；本次 fixture 最终统一回退为 `Table 5. Medium-density STM32F103xx pin definitions`。
- 本次直接 fixture 观察结果：
  - `PD0`：`short_answer` 仍是 `Different source candidates disagree on the pin mapping for PD0: Rev 17 shows -; Rev 20 shows D8.`；`sources[0].section` / `sources[1].section` 与 `key_evidence` 都不再出现 `Ϯ`、`Pc13-Tamper-Rtc`。
  - `PD1`：`short_answer` 仍是 `Different source candidates disagree on the pin mapping for PD1: Rev 17 shows -; Rev 20 shows E8.`；`sources[*].section` 与 `key_evidence` 同步清理为干净 table caption。
- 本次执行并确认通过的命令：
  - `python E:\Aiskillls\.trellis\scripts\embedded_lookup_fixed_regression.py --include-phase2-stm32f103-revision-conflict-rerun`
  - `python E:\Aiskillls\.trellis\scripts\embedded_lookup_fixed_regression.py --include-phase2-feature-ordering --include-phase2-stm32f103-revision-conflict-rerun`
- 当前结果：
  - `phase2-stm32f103-revision-conflict-rerun`：PASS
  - `phase2-feature-ordering`：PASS
  - combined blocking verdict：PASS
- 本次后剩余风险：
  - 本次 `section` 归一化只作用于 pin conflict 返回层；其他 query family 或非 conflict pin 路径里的 heading 噪声仍保持现状。
  - caption 回退目前依赖当前 evidence 文本里能否提取到 `Table N ... pin definitions`；若后续遇到没有 table caption、只有高度破碎 OCR 的冲突样本，可能还需要再补更保守的通用 `Pin definitions table` 回退。

## 当前状态总览

- 项目根目录：`E:/Aiskillls/embedded-manual-lookup`
- 当前主题：datasheet table-aware retrieval 增强
- 当前阶段：
  - Phase 1 已闭环
  - 2026-04-01 时，03-31 的 feature / ordering table 链路及其 regression packaging 已完成并有 PASS 结果
- 当前暂停点：
  - `03-31-table-aware-feature-ordering-routing`：已完成并验证
  - `03-31-table-aware-feature-ordering-row-selection`：已完成并验证
  - `03-31-table-aware-feature-ordering-constraint-gate`：已完成，不再处于收敛阶段
  - `03-31-table-aware-feature-ordering-regression-packaging`：已完成并验证
  - `04-02-package-ordering-device-variant-sibling-ambiguity-refusal`：已完成并验证
- 续作方向：
  - 如果沿 03-31 这条线继续，默认前提应是当前 Phase 2 runner / combined run / refusal probes 已是既成基线，而不是回头继续做 gate 收敛或补 packaging

## 接手前先确认

开始前，先确认下面三句话仍然成立：

1. Phase 1 已封板，不再扩 scope，也不要借 03-31 任务回滚成 Phase 1 重构。
2. 03-31 的 `routing`、`row-selection`、`constraint-gate`、`regression-packaging` 都已完成；`phase2-feature-ordering`、combined run、package refusal、flash refusal 都已有 PASS 结果。
3. 当前不存在“先做 gate 收敛、再做 packaging”的前置依赖；如果要继续推进，应基于现有 PASS 基线定义新任务，而不是把旧任务当成未完成。

如果这三条里有任何一条不成立，就先重新核对 Trellis 任务链和 runtime 现状，不要直接改代码。

## 当前工作树状态

以下状态是在本次整理文档时看到的：

- 分支：`master`
- 工作树不是干净状态
- 当前可见改动：
  - `scripts/embedded_lookup.py`：已修改
  - `.gitignore`：未跟踪
  - `HANDOFF.md`：未跟踪
  - `scripts/__pycache__/`：未跟踪

接手时请注意：

- 不要默认把 `scripts/embedded_lookup.py` 当成“可放心覆盖”的文件
- 先看清该文件现有未提交改动是不是本轮工作遗留
- `__pycache__` 不应作为交付物的一部分

## 已完成工作

### 1. Phase 1 已封板

Phase 1 主线已经闭环，不建议在没有新任务的情况下回头改 scope：

- pin-definition / electrical-parameter routing 已完成
- row-level evidence selection 已完成
- constraint-aware gate 已完成
- fixed probes and regression packaging 已完成
- missing-package strict refusal 已完成
- missing-remap strict refusal 已完成
- fixed runner 已对齐真实 runtime 路径，并把 strict-refusal probes 纳入 `phase1-table-aware` lane

### 2. 03-31 feature / ordering 阶段已完成部分

- `routing` 已完成并验证
  - family 路由已正确进入 feature / peripheral-count / memory / package / ordering / device-variant 相关 table family
  - 但仅靠 routing 还不足以修正最终答案
- `row-selection` 已完成并验证
  - top evidence 已回到正确 row-cluster
  - 这一步任务之后的 gate / packaging 也已补齐验证，03-31 这条 feature / ordering 链路当前可视为已完成

### 3. 当前明确未完成部分

- 就本次 handoff 覆盖的 03-31 / Phase 2 链路而言，当前没有“必须先补完”的 gate / packaging 遗留项
- 当前已完成并确认 PASS 的新增验证包括：
  - `phase2-feature-ordering`
  - `phase1-table-aware + phase2-feature-ordering` combined run
  - `phase2-package-stm32f103c8-refusal`
  - `phase2-flash-stm32f103c8-refusal`
  - `phase2-ordering-stm32f103c8-refusal`
- 如果后续还要继续扩展能力，应视为新任务，而不是把当前链路重新标记回 `in_progress`

### 4. 2026-03-31 本轮续作已落地的增量

- `embedded_lookup.py` 的 `_apply_constraint_aware_answer_gate()` 已接入：
  - `feature`
  - `peripheral-count`
  - `memory`
  - `package`
  - `ordering`
  - `device-variant`
- package identity 问句已从 pin gate 误分类中拉回 `TABLE_QUESTION_PACKAGE`
- table-family 正向命中时，grounded short answer 已补到更像完成态的输出
  - 已确认示例：
    - `How many ADCs does STM32F103x8B provide?`
    - 当前会直接输出 `two 12-bit ADCs` 的 grounded answer
- 一部分纯问句功能词的噪声 open-question 已被抑制
  - 正向 feature probe 不再出现 `how / many / does / provide` 这类假缺口提示

## 已确认事实

### 1. Phase 1 验证结论

依据：

- `E:/Aiskillls/.trellis/tasks/03-30-table-aware-fixed-probes-and-regression-packaging/validation-report.md`
- `E:/Aiskillls/.trellis/tasks/03-30-table-aware-missing-remap-strict-refusal-packaging/validation-report.md`

已确认：

- fixed regression runner 默认 runtime target 已切换到：
  - `E:/Aiskillls/embedded-manual-lookup/scripts/embedded_lookup.py`
- runner lane 结构已稳定保留：
  - `baseline-blocking`
  - `extended-conservative`
  - `phase1-table-aware`
- 2026-03-30 验证记录显示：
  - `baseline-blocking`：PASS
  - `extended-conservative`：PASS
  - `phase1-table-aware`：PASS
- missing-remap sibling probe 已纳入 `phase1-table-aware`
- missing-remap strict refusal 已有实测证据，不是只停留在文档层

### 2. 03-31 阶段已确认的工程事实

从当前 runtime 可以确认，feature / ordering 相关 family、row-selection 入口和 Phase 1 gate 框架已经存在于：

- `E:/Aiskillls/embedded-manual-lookup/scripts/embedded_lookup.py`

当前已能明确看到的触点包括：

- question family 常量：
  - `TABLE_QUESTION_FEATURE`
  - `TABLE_QUESTION_ORDERING`
  - `TABLE_QUESTION_DEVICE_VARIANT`
- section / chunk / row 相关入口：
  - `_score_chunks()`
  - `_supports_table_row_selection()`
  - `_table_row_candidate_bonus()`
- 现有 gate 主入口：
  - `_apply_constraint_aware_answer_gate()`

当前可以确认的判断：

- 03-31 的 `routing` 和 `row-selection` 已进入 runtime 主文件，不是只停留在 Trellis 文档
- `constraint-gate` 已不再只覆盖 pin / electrical；feature-ordering 相关 family 的 gate 接入与后续 packaging 已形成通过验证的完成态
- 当前 handoff 不应再把 feature / ordering 家族描述成“仍在 gate 收敛中”

## 当前 Trellis 任务链

### Phase 1 已闭环链路

建议按下面顺序回看：

1. `E:/Aiskillls/.trellis/tasks/03-30-table-aware-question-routing-and-section-ranking/task-spec.md`
2. `E:/Aiskillls/.trellis/tasks/03-30-table-aware-row-level-evidence-selection/task-spec.md`
3. `E:/Aiskillls/.trellis/tasks/03-30-table-aware-constraint-aware-answer-gate/task-spec.md`
4. `E:/Aiskillls/.trellis/tasks/03-30-table-aware-fixed-probes-and-regression-packaging/task-spec.md`
5. `E:/Aiskillls/.trellis/tasks/03-30-table-aware-strict-refusal-regression-packaging/task-spec.md`
6. `E:/Aiskillls/.trellis/tasks/03-30-table-aware-missing-constraint-conservative-refusal/task-spec.md`
7. `E:/Aiskillls/.trellis/tasks/03-30-table-aware-missing-remap-strict-refusal-packaging/task-spec.md`

### 03-31 feature / ordering 链路

当前链路已经定义完整，当前真实进度如下：

1. `E:/Aiskillls/.trellis/tasks/03-31-table-aware-feature-ordering-routing/task-spec.md`
2. `E:/Aiskillls/.trellis/tasks/03-31-table-aware-feature-ordering-row-selection/task-spec.md`
3. `E:/Aiskillls/.trellis/tasks/03-31-table-aware-feature-ordering-constraint-gate/task-spec.md`
4. `E:/Aiskillls/.trellis/tasks/03-31-table-aware-feature-ordering-regression-packaging/task-spec.md`

当前接力规则：

- `03-31-table-aware-feature-ordering-routing`：`completed`
- `03-31-table-aware-feature-ordering-row-selection`：`completed`
- `03-31-table-aware-feature-ordering-constraint-gate`：`completed`
- `03-31-table-aware-feature-ordering-regression-packaging`：`completed`
- Phase 2 回归结果：
  - `phase2-feature-ordering`：`PASS`
  - `phase1-table-aware + phase2-feature-ordering` combined run：`PASS`
  - `phase2-package-stm32f103c8-refusal`：`PASS`
  - `phase2-flash-stm32f103c8-refusal`：`PASS`
  - `phase2-ordering-stm32f103c8-refusal`：`PASS`
- 当前明确状态不是“继续第三步”，而是 03-31 这条链路已完成；若再继续，应新开任务而不是续做旧 gate

## 关键文件与作用

### 运行时代码

- `E:/Aiskillls/embedded-manual-lookup/scripts/embedded_lookup.py`
  - 当前所有 table-aware runtime 逻辑都在这里
  - 03-31 继续推进时，核心修改面仍应集中在这个文件

### 固定回归入口

- `E:/Aiskillls/.trellis/scripts/embedded_lookup_fixed_regression.py`
  - 这是 sibling 目录 `.trellis/` 下的脚本，不在仓库根目录内部
  - 已对齐真实 runtime 路径
  - Phase 1 的 fixed probes / strict refusal packaging 都以它为基准
  - 03-31 完成后，feature / ordering 的 probe packaging 大概率也应复用这里，而不是新开 runner

### 关键验证文件

- `E:/Aiskillls/.trellis/tasks/03-30-table-aware-fixed-probes-and-regression-packaging/validation-report.md`
- `E:/Aiskillls/.trellis/tasks/03-30-table-aware-strict-refusal-regression-packaging/validation-report.md`
- `E:/Aiskillls/.trellis/tasks/03-30-table-aware-missing-constraint-conservative-refusal/validation-report.md`
- `E:/Aiskillls/.trellis/tasks/03-30-table-aware-missing-remap-strict-refusal-packaging/validation-report.md`
- `E:/Aiskillls/.trellis/tasks/03-31-table-aware-feature-ordering-constraint-gate/task-spec.md`
- `E:/Aiskillls/.trellis/tasks/03-31-table-aware-feature-ordering-regression-packaging/task-spec.md`

### 本轮追加验证结论

基于当前 runtime 手工验证，已确认：

- `python .\\scripts\\embedded_lookup.py --help`
  - PASS
- `How many ADCs does STM32F103x8B provide?`
  - 已能输出 grounded positive short answer
- `How much Flash and SRAM does STM32F103CB provide?`
  - 仍保持 conservative，不会把 sibling-ambiguous `64 or 128 Kbytes` 直接放行为正向答案
- `Which ordering code corresponds to the LQFP48 package for STM32F103CB?`
  - 仍保持 conservative，且不再误走 pin gate
- `Which package does STM32F103C8 use?`
  - 已不再误走 pin gate，当前保持 conservative
- `python ..\\.trellis\\scripts\\embedded_lookup_fixed_regression.py`
  - `baseline-blocking`: PASS
  - `phase2-feature-ordering`: PASS
  - `phase1-table-aware + phase2-feature-ordering` combined run: PASS
  - `phase2-package-stm32f103c8-refusal`: PASS
  - `phase2-flash-stm32f103c8-refusal`: PASS
  - `phase2-ordering-stm32f103c8-refusal`: PASS

## 下一步应该做什么

### 1. 先把 2026-04-01 的 PASS 结果当成当前基线

当前不应再把工作起点定义成“继续完成 feature / ordering constraint gate”。更合理的起点是：

- 先承认 03-31 这条 feature / ordering 链路及其 regression packaging 已完成
- 后续任何新增工作都应以现有 PASS lane 和 refusal probe 为保护基线
- 不要为了“再确认一次”而把已完成的 gate / packaging 重新打开

### 2. 如果继续推进，按新任务处理，而不是回到旧 gate

如果后续还有新范围，建议只做下面几类事情：

- 基于 `E:/Aiskillls/.trellis/scripts/embedded_lookup_fixed_regression.py` 扩新 probe，而不是重开旧 packaging
- 保持既有 `baseline-blocking` / `extended-conservative` / `phase1-table-aware` / `phase2-feature-ordering` 语义不漂移
- 把 package / flash refusal 的现有 PASS 当成 guardrail，不要在后续修改里弱化

## 建议阅读顺序

如果需要快速进入状态，建议按下面顺序看：

1. 先读 `E:/Aiskillls/embedded-manual-lookup/HANDOFF.md`
2. 再读 `E:/Aiskillls/.trellis/tasks/03-31-table-aware-feature-ordering-regression-packaging/task-spec.md`
3. 对照当前已通过的 Phase 2 结果，核对 fixed runner 与 refusal probes 的口径
4. 如果确实要继续扩展，再回看 `E:/Aiskillls/.trellis/tasks/03-31-table-aware-feature-ordering-constraint-gate/task-spec.md` 和相关 runtime 决策点，但不要把它们当成“当前尚未完成的旧任务”

## 建议改动边界

当前续作建议控制在下面边界内：

- 主要改动目标：`E:/Aiskillls/embedded-manual-lookup/scripts/embedded_lookup.py`
- 验证与 packaging 入口：`E:/Aiskillls/.trellis/scripts/embedded_lookup_fixed_regression.py`
- 不建议在当前轮次同时做的事：
  - 重写 routing
  - 重写 row-selection
  - 调整 Phase 1 lane 语义
  - 新开一套与 fixed runner 并行的回归入口

## 完成判定

只有同时满足下面条件，才能认为 03-31 这条线继续推进成功：

1. feature / ordering 相关 family 已有明确的 go / no-go gate，而不是仅靠 top evidence 排名。
2. sibling row、模糊 suffix、未充分约束的 package / ordering 场景不会被误放行为 confident positive answer。
3. 现有 ambiguity / conflict / conservative guardrail 没有被削弱。
4. gate 行为有对应验证证据。
5. packaging 进入固定 runner 时，没有偷改既有 lane 的语义。

## 验证入口

已知相关入口包括：

- 运行时帮助：
  - `python .\\scripts\\embedded_lookup.py --help`
- 固定回归入口：
  - `python ..\\.trellis\\scripts\\embedded_lookup_fixed_regression.py`

说明：

- 上述第二个命令使用的是仓库同级目录 `E:/Aiskillls/.trellis/`
- 本文档整理时没有重新执行这些回归；这里只记录当前约定入口，供接手人继续验证使用

## 已知风险与不要做的事

- 不要误判为“检索已经修好，只差一点格式化”。
- 不要把当前状态误写回“`constraint-gate` 仍未完成、packaging 尚未开始”；这会把已经通过的结果降格成错误 handoff。
- package / ordering / device-variant 这组问题天然有 sibling ambiguity 风险，最容易出现“邻近行几乎正确但并非目标 device”的误放行。
- 必须继续保持 conservative bias：
  - 宁可拒答，也不要对 sibling row、模糊 suffix 或未充分约束的 package 问题给出看似自信的正向答案
- fixed runner 已明确绑定真实 runtime 路径；如果再看到 `.agents/skills/embedded-lookup/scripts/embedded_lookup.py`，应仅作历史参考，不要重新把它当成主目标

## 接手执行清单

建议下一位接手人按下面顺序推进：

1. 确认 `scripts/embedded_lookup.py` 当前未提交改动的来源，不要盲改。
2. 先把 `phase2-feature-ordering`、combined run、package refusal、flash refusal、ordering refusal 均已 PASS 视为当前基线，不要按“旧任务未完成”开工。
3. 重读 `03-31-table-aware-feature-ordering-regression-packaging/task-spec.md`，确认当前 handoff 与 Phase 2 lane 命名、runner 口径一致。
4. 如果要继续推进，只能以“新任务”方式扩展，不要回头重写 routing / row-selection，也不要把旧 gate 重新标回 `in_progress`。
5. 任何新增修改都先对照固定 runner，确认没有破坏既有 `baseline-blocking` / `extended-conservative` / `phase1-table-aware` / `phase2-feature-ordering` 结果。
6. 尤其要保住 `phase2-package-stm32f103c8-refusal`、`phase2-flash-stm32f103c8-refusal` 和 `phase2-ordering-stm32f103c8-refusal` 的 PASS 表现。

## 2026-04-05 环境状态补充

- 当前 Python 环境已安装 `pdfplumber 0.11.9`。
- 已执行最小导入验证：
  - `python -c "import pdfplumber; print(pdfplumber.__version__)"`
- 已执行最小运行验证：
  - `python .\scripts\embedded_lookup.py ".\fixtures\stm32f103-revision-conflict-pd0pd1\stm32f103cb.pdf" "STM32F103x8B 的 VDD 工作电压范围是多少？" --pdf-backend pdfplumber --device STM32F103x8B --document-type datasheet --json`
- 本次验证结果：
  - CLI 在 `--pdf-backend pdfplumber` 下可正常运行，不再因缺少可选依赖而失败。
  - 上述查询返回 `electrical_parameter` 结构化结果，`VDD operating voltage` 为 `2.0 to 3.6 V`。

## 2026-04-05 focused screening：3 个 family 是否适合进入下一轮 fixed regression 扩面

本轮只做 focused screening，不改 runtime 源码；验证入口仍复用：

- `python E:\Aiskillls\.trellis\scripts\embedded_lookup_fixed_regression.py --include-extended --include-phase1-table-aware --include-phase2-feature-ordering`
- 必要时补跑少量 `python E:\Aiskillls\embedded-manual-lookup\scripts\embedded_lookup.py ... --json` 直查输出形态

### 1. `LQFP48 TX`

- 当前 probe / lane：
  - `ds-lqfp48-usart1-tx` -> `extended-conservative`
  - `phase1-table-pin-lqfp48-usart1-tx` -> `phase1-table-aware`
- 当前事实：
  - 本轮 fixed runner 中，上述两个 probe 都是 `PASS`。
  - 直跑 `Which pin provides USART1_TX on STM32F103x8B in the LQFP48 package?` 仍返回 grounded positive：
    - `short_answer` 明确落到 `USART1_TX -> PA9 / PA9 for LQFP48`
    - `structured_summary.kind = "pin"`
    - `Package / Variant = LQFP48`
    - `open_questions = []`
- 稳定性判断：
  - 约束命中是稳定的；当前不会退化成 refusal，也没有漂移成 parameter-style answer。
  - 但 pin 文案仍表现为 `PA9 / PA9`，说明答案归一化还有重复值表现；这不影响当前 probe 通过，但代表它更适合被视为“语义稳定、表述未完全打磨完”的正向 family。
- 是否建议进入下一轮扩面：
  - 建议：`是`
  - 建议挂载 lane：`phase1-table-aware`
  - 补充约束：保留 `extended-conservative` 里的历史 probe 作为 advisory drift guard，但不要把“datasheet LQFP48 wording family”重新定义成新的 baseline-blocking 扩面入口。

### 2. `missing-package sibling`

- 当前 probe / lane：
  - `phase1-missing-package-usart1-tx-refusal` -> `phase1-table-aware`
- 当前事实：
  - 本轮 fixed runner 中该 probe 为 `PASS`。
  - 直跑 `Which pin provides USART1_TX on STM32F103x8B?` 当前输出为 conservative refusal：
    - 没有 `structured_summary`
    - 没有 concrete pin answer
    - `open_questions` 明确要求补充 `package or package variant`
- 稳定性判断：
  - 该 family 当前是稳定拒答；已经不再回退成“给一个 pin-shaped answer 再附带 cautionary open questions”。
  - 其 refusal 触发点与缺失约束语义一致，适合作为 phase-one guardrail 继续扩。
- 是否建议进入下一轮扩面：
  - 建议：`是`
  - 建议挂载 lane：`phase1-table-aware`
  - 补充约束：应继续保持 non-blocking strict-refusal family 的语义，不要把这类 sibling refusal 改造成新的 positive lane。

### 3. `C8/CB package-ordering sibling ambiguity`

- 当前 probe / lane：
  - `phase2-ordering-stm32f103c8-refusal` -> `phase2-feature-ordering`
  - `phase2-package-stm32f103c8-refusal` -> `phase2-feature-ordering`
  - 同 lane 的 exact positive 对照为 `phase2-ordering-stm32f103cb-lqfp48`
- 当前事实：
  - 本轮 fixed runner 中：
    - `phase2-ordering-stm32f103cb-lqfp48`: `PASS`
    - `phase2-ordering-stm32f103c8-refusal`: `PASS`
    - `phase2-package-stm32f103c8-refusal`: `PASS`
  - 直跑 exact positive：
    - `Which ordering code corresponds to the LQFP48 package for STM32F103CB?`
    - 当前仍返回 grounded positive：`package code T corresponds to LQFP48`
    - `open_questions = []`
  - 直跑 sibling-ambiguous refusal：
    - `Which ordering code corresponds to the LQFP48 package for STM32F103C8?`
    - `Which package does STM32F103C8 use?`
    - 当前都返回 conservative refusal，没有 `structured_summary`
    - `open_questions` 都明确指出：`The retrieved package/ordering row did not preserve a grounded device/package mapping.`
- 稳定性判断：
  - “CB exact 可答、C8 sibling 继续拒答”的边界当前是稳定的。
  - 这类 family 的价值在于 guardrail，而不是证明 `STM32F103C8` 已具备可放行的 exact ordering/package coverage。
- 是否建议进入下一轮扩面：
  - 建议：`是，但仅限 refusal / guardrail 扩面`
  - 建议挂载 lane：`phase2-feature-ordering`
  - 补充约束：不要把 `STM32F103C8` 的 package / ordering sibling 场景升级成 blocking positive coverage，除非后续先拿到 exact variant closure 证据。

## focused screening 总结结论

- 可以进入下一轮 fixed regression 扩面的 family：
  - `LQFP48 TX`
    - 作为 package-constrained positive family 继续扩，但主要挂在 `phase1-table-aware`
  - `missing-package sibling`
    - 作为缺失约束 refusal family 继续扩，挂在 `phase1-table-aware`
  - `C8/CB package-ordering sibling ambiguity`
    - 作为 sibling ambiguity refusal / guardrail family 继续扩，挂在 `phase2-feature-ordering`
- 当前不建议的动作：
  - 不要把 `LQFP48 TX` 重新解释成新的 baseline-blocking datasheet family
  - 不要把 `C8/CB` family 误读成 “STM32F103C8 ordering/package 已经可以正向放行”
- 当前唯一需要额外记住的不稳定点：
  - `LQFP48 TX` 的答案文案仍出现 `PA9 / PA9` 重复值；这更像表述归一化问题，而不是 family 稳定性问题。若后续要追求更干净的 fixed sample，可在不改变 lane 语义的前提下再单独处理。

## 2026-04-05 LQFP48 TX fallback pin token dedupe 最小修复

- 修改文件：
  - `E:/Aiskillls/embedded-manual-lookup/scripts/embedded_lookup.py`
- 修改范围：
  - 只在 `_extract_pin_mapping_values()` 的 `signal_or_function` fallback 分支，对 `PIN_NAME_RE.findall(line)` 提取出的 `line_pins` 做保序去重。
  - 只在 `_build_pin_grounded_short_answer()` 的同类 fallback 里，对目标行提取出的 `row_pins` 做保序去重。
  - 未改动 pin/package/revision conflict 主逻辑，也未引入全局 slash-joined 归一化。
- 修复事实：
  - 之前 `LQFP48 TX` 的 datasheet row 会把同一行里的 `PA9` 命中为重复 token，导致 `fallback_value = " / ".join(row_pins)` 输出 `PA9 / PA9`。
  - 现在同一路径会先保序去重，因此 `structured_summary.Pin Name` 和 grounded `short_answer` 都收敛为 `PA9`。
- 本次验证命令与结果：
  - `python E:\Aiskillls\embedded-manual-lookup\scripts\embedded_lookup.py "E:/Aiskillls/手册参考/STM32F103x8B数据手册（英文）.pdf" "Which pin provides USART1_TX on STM32F103x8B in the LQFP48 package?" --device STM32F103x8B --document-type datasheet --json`
    - PASS
    - `short_answer`: `The strongest grounded evidence indicates that USART1_TX maps to PA9 for LQFP48 ...`
    - `structured_summary.kind = "pin"`
    - `structured_summary.Pin Name = "PA9"`
    - `structured_summary.Package / Variant = "LQFP48"`
    - `open_questions = []`
  - `python E:\Aiskillls\.trellis\scripts\embedded_lookup_fixed_regression.py --include-extended --include-phase1-table-aware --include-phase2-feature-ordering`
    - PASS
    - `ds-lqfp48-usart1-tx`: PASS
    - `phase1-table-pin-lqfp48-usart1-tx`: PASS
    - `phase1-table-electrical-vdd`: PASS
    - `phase1-missing-package-usart1-tx-refusal`: PASS
    - `phase1-missing-remap-usart1-tx-refusal`: PASS
    - `phase2-feature-count-adcs-stm32f103x8b`: PASS
    - `phase2-memory-stm32f103cb-flash-sram`: PASS
    - `phase2-ordering-stm32f103cb-lqfp48`: PASS
    - `phase2-ordering-stm32f103c8-refusal`: PASS
    - `phase2-package-stm32f103c8-refusal`: PASS
    - `phase2-flash-stm32f103c8-refusal`: PASS
- 风险与未处理项：
  - 显式加上 `--pdf-backend pdfplumber` 后，同一 `LQFP48 TX` 直跑当前仍会返回 conservative refusal，失败签名包含：
    - `short_answer = "No grounded answer found yet; ..."`
    - `open_questions` 提示 `The retrieved pin row did not preserve the requested package constraint (LQFP48).`
  - 该 backend 差异在本次最小修复前后都不属于 `PA9 / PA9` 重复 token 的问题面，本次未扩大处理范围。

## 2026-04-05 fixed regression checker hardening

- 修改文件：
  - `E:/Aiskillls/.trellis/scripts/embedded_lookup_fixed_regression.py`
  - `E:/Aiskillls/embedded-manual-lookup/HANDOFF.md`
- 本次目标：
  - 只把 fixed regression 中 `phase1-table-pin-lqfp48-usart1-tx` 的 checker 从宽松包含断言收紧为精确冻结 `PA9 / PA9 -> PA9` 这次修复。
  - 不新增 case，不改 runner / lane 语义，不扩到 `missing-package sibling` 或 `C8/CB` family。
- checker 收紧内容：
  - `structured_summary.Pin Name` 由原先 `contains("PA9")` 改为精确断言 `== "PA9"`。
  - 新增断言：`short_answer` 不得再出现 `PA9 / PA9`。
  - `observed` 附带 `short_answer_has_dup=<bool>`，便于失败时直接看出是否回归到重复 pin 文案。
- 最小验证命令与结果：
  - `python E:\Aiskillls\.trellis\scripts\embedded_lookup_fixed_regression.py --include-phase1-table-aware`
    - PASS
    - `phase1-table-pin-lqfp48-usart1-tx`: PASS
    - `phase1-table-electrical-vdd`: PASS
    - `phase1-missing-package-usart1-tx-refusal`: PASS
    - `phase1-missing-remap-usart1-tx-refusal`: PASS
- 风险与不确定性：
  - 这次只冻结 phase1-table-aware lane 内的既有 probe；如果后续其他路径重新生成重复 pin 文案，当前 hardening 不会替代更广范围的回归覆盖。

## 2026-04-05 missing-package USART1_RX sibling refusal 补点

- 修改文件：
  - `E:/Aiskillls/.trellis/scripts/embedded_lookup_fixed_regression.py`
  - `E:/Aiskillls/embedded-manual-lookup/HANDOFF.md`
- 本次目标：
  - 只把 `USART1_RX` 的 missing-package sibling refusal case 以最小改动补进 `phase1-table-aware` fixed regression。
  - 保持与现有 `phase1-missing-package-usart1-tx-refusal` 相同的 non-blocking strict-refusal 语义，不扩到 parser/backend、revision-conflict、phase2 ordering，也不新增 lane。
- runner 变更：
  - 在 `phase1-table-aware` 新增 `phase1-missing-package-usart1-rx-refusal`。
  - query 固定为 `Which pin provides USART1_RX on STM32F103x8B?`，`--device STM32F103x8B --document-type datasheet --json`。
  - 继续复用现有 `_check_phase1_missing_constraint_refusal()`；未新增 checker 分支。
- 本次验证命令与结果：
  - `python E:\Aiskillls\.trellis\scripts\embedded_lookup_fixed_regression.py --include-phase1-table-aware`
    - PASS
    - `phase1-table-pin-lqfp48-usart1-tx`: PASS
    - `phase1-table-electrical-vdd`: PASS
    - `phase1-missing-package-usart1-tx-refusal`: PASS
    - `phase1-missing-package-usart1-rx-refusal`: PASS
    - `phase1-missing-remap-usart1-tx-refusal`: PASS
- 验证结论：
  - `USART1_RX` missing-package sibling 当前已被固定 runner 覆盖，并保持 conservative refusal。
  - 该补点没有改变 `phase1-table-aware` 的 lane 语义；新增 case 仍是 non-blocking guardrail，而不是正向 pin coverage。
- 风险与不确定性：
  - 当前只冻结 missing-package refusal family 在 fixed runner 的存在性与 refusal 形态；如果后续运行时改写 open-question 文案但仍保持同类拒答，probe 仍依赖现有 missing-constraint token 检查逻辑。

## 2026-04-05 C8/CB package-ordering sibling ambiguity package-side guardrail 补点

- 修改文件：
  - `E:/Aiskillls/.trellis/scripts/embedded_lookup_fixed_regression.py`
  - `E:/Aiskillls/embedded-manual-lookup/HANDOFF.md`
- 本次目标：
  - 只把 `C8/CB package-ordering sibling ambiguity` 的 package-side 最小 refusal guardrail case 补进 `phase2-feature-ordering` fixed regression。
  - 不扩到 parser/backend、phase1、revision-conflict，也不新增 lane 或任何 `STM32F103C8` 正向 coverage。
- runner 变更：
  - 在 `phase2-feature-ordering` 新增 `phase2-package-code-stm32f103c8-refusal`。
  - query 固定为 `Which package does package code T correspond to for STM32F103C8?`，`--device STM32F103C8 --document-type datasheet --json`。
  - 继续复用现有 `_check_phase2_conservative_refusal()`；只把 required token 最小扩到 `("package", "ordering", "code", "variant", "suffix")`，未新增定向 checker。
- 只读直查事实：
  - 当前 query 会命中 `7 > Ordering information scheme (page 104)`，`sources[0].excerpt` 仍可看到 `T = LQFP` 与 `STM32F103C8 package = LQFP48`。
  - 但运行时输出仍是 conservative refusal，没有 `structured_summary`。
  - `open_questions` 保留了 `The retrieved package/ordering row did not preserve a grounded device/package mapping.`，并额外提示 `Top evidence still missed these query terms: code.`。
- 本次验证命令与结果：
  - `python E:\Aiskillls\.trellis\scripts\embedded_lookup_fixed_regression.py --include-phase2-feature-ordering`
    - PASS
    - `phase2-feature-count-adcs-stm32f103x8b`: PASS
    - `phase2-memory-stm32f103cb-flash-sram`: PASS
    - `phase2-ordering-stm32f103cb-lqfp48`: PASS
    - `phase2-ordering-stm32f103c8-refusal`: PASS
    - `phase2-package-stm32f103c8-refusal`: PASS
    - `phase2-package-code-stm32f103c8-refusal`: PASS
    - `phase2-flash-stm32f103c8-refusal`: PASS
- 验证结论：
  - `phase2-feature-ordering` 现在同时覆盖 ordering-side 与 package-side 的 `C8/CB` sibling ambiguity refusal。
  - 新增 case 仍是 non-blocking guardrail，作用是冻结“命中 ordering row 但仍应拒答”的保守边界，而不是放宽 `STM32F103C8` package/ordering 的正向能力口径。
- 风险与不确定性：
  - 当前 probe 仍依赖现有 refusal checker 的 open-question token 匹配；如果后续运行时改写 refusal 文案但保持同类保守行为，这个 probe 可能需要跟随更新。
  - `Top evidence still missed these query terms: code.` 反映的是当前 query wording 与 row 文本之间的词面差异，不应被误读成可以安全放行 package-side positive answer 的信号。
