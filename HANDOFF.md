# embedded-manual-lookup 接力文档

更新时间：`2026-04-02`

## 一句话结论

当前真正的续作起点不是重做 retrieval，也不是继续收敛 `constraint-gate`，而是把 2026-04-02 已验证通过的 Phase 2 结果当成新的续作基线。  
Phase 1 已封板；`phase2-feature-ordering` runner 已 PASS；`phase1-table-aware + phase2-feature-ordering` combined run 已 PASS；`phase2-package-stm32f103c8-refusal` 已 PASS；`phase2-flash-stm32f103c8-refusal` 已 PASS；`phase2-ordering-stm32f103c8-refusal` 已 PASS；`04-02-package-ordering-device-variant-sibling-ambiguity-refusal` 已完成；`regression-packaging` 已完成。

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
