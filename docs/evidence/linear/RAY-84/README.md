# RAY-84 Evidence

- Issue：`RAY-84` 检测中视图：48×64 热力图、COP 与必要状态
- URL：https://linear.app/ray-app/issue/RAY-84/检测中视图4864-热力图cop-与必要状态
- 初次抓取时间：2026-07-20T08:54:41Z
- 开始实现时间：2026-07-20T10:28:25Z
- 初次抓取状态：Backlog
- 当前工作流状态：In Review（2026-07-20T10:35:22Z 写入并重新读取确认）
- 里程碑：P2：一键筛查
- 优先级：High
- 关系：无阻塞、被阻塞或 related issue

## 验收条目快照

- [x] 48×64 热力图；显示插值不暗示超过约 12 Hz 的新数据
- [x] COP 当前点/最多 24 点短轨迹、左右/总相对负重及最多 60 点总量趋势模型
- [x] 剩余时间、站位提示、采集中状态和单一停止动作
- [x] UI latest-only 邮箱覆盖旧显示帧且没有可靠存储写接口
- [x] 高 DPI 自绘、大字号、可访问名称、键盘按钮和色彩/文字双重表达
- [x] 沿用稳定错误编号与通俗动作，不把设备异常/堆栈放入显示模型
- [x] 显示帧停滞时工作流倒计时仍独立准确；线程安全并发发布测试通过

## 实现文件与关键决策

- `client/local_analysis/display.py`：不可变 `DisplayFrame`、48×64 相对矩阵、COP/短轨迹、左右/总量与趋势、线程安全 `LatestDisplayFrameMailbox`、独立刷新节流器。
- `client/app/heatmap.py`：Qt 高 DPI 自绘热力图；64×48 原始显示栅格可平滑放大，COP/轨迹为矢量叠加；不生成分析数据。
- `client/app/qt_shell.py`：P-07 接入热力图、COP 文字、左右/总量、设备帧序号与“显示不代表提高采样率”说明，保留剩余时间/提示/状态/单一停止。
- `client/app/controller.py`：可选 display refresh 事件；无新帧时不伪造序号/时间，工作流 elapsed 事件独立刷新剩余时间。
- `client/tests/test_ray_84_*.py`：形状/不可变、latest-only、线程安全、30 Hz 最大 UI 刷新、时间戳真实性、Qt render、文字冗余和显示停滞注入。

关键决策：采集端可在可靠落盘后把派生显示帧发布到 latest-only 邮箱；邮箱只保存最高 sequence 的一帧，无任何存储/上传方法，UI 卡顿只丢显示帧；Qt 最多 30 Hz 检查最新帧，但只有新 sequence 才更新，设备时间戳原样保留；热力图平滑只影响视觉，COP/指标仍来自未插值 48×64 输入。

## 验证命令与结果

执行时间：2026-07-20T10:32:02Z。

```bash
QT_QPA_PLATFORM=offscreen /private/tmp/feetforceplate-subtask-b-venv/bin/python \
  -m pytest client/tests -q \
  --junitxml=docs/evidence/linear/RAY-84/pytest-results.xml
```

结果：`80 passed`；包含 RAY-84 自动测试以及此前客户端 issue 的完整回归。

```bash
/private/tmp/feetforceplate-subtask-b-venv/bin/python -m compileall -q \
  client/app client/workflow client/local_analysis client/reporting client/tests
```

结果：通过。

```bash
! rg -n "^(import|from) (serial|sqlite3|requests|httpx|urllib|aiohttp)" \
  client/app client/workflow client/local_analysis client/reporting
```

结果：0 命中。

界面证据：[P-07-live-heatmap.png](P-07-live-heatmap.png)（Qt offscreen 合成数据，已目视检查；不是目标 Windows/真人站立验收）。

## 自动测试、真机与人工边界

- 已自动验证：48×64 不可变显示帧；75/25 左右负重与 COP；旧帧覆盖不影响独立可靠序列；并发 100 帧最终取最高 sequence；30 Hz 节流不伪造设备帧；Qt 高 DPI raster+vector render 非空；色彩旁同时有 COP/负重文字；无新显示/上传事件时倒计时仍到 00:25。
- 尚未验证：真实 DO-P4864 的约 12 Hz 帧流、实际压力脚印和 COP；采集线程/上传线程真实卡顿与操作系统调度；Windows 100/125/150/200% 缩放；目标显示器色彩/对比；键盘焦点可见性；色觉差异；现场操作员对停止确认和信息密度的人工验收。
- 因上述真机/人工项未完成，本 issue 只能进入 `In Review`，不得标 `Done`。

## 失败或限制

- screenshot 使用矩形合成双足区域，只证明渲染和布局，不证明真实足印视觉质量或医学含义。
- `total_trend` 已在显示模型保留最多 60 点，但首版 P-07 仅显示当前左右/总量文字；趋势曲线是 issue 中的可选项，待真实采集节奏与现场信息密度评审后再开放。
- Qt offscreen 无法替代 Windows 高 DPI、键盘焦点和真实显示器色彩测试。

## 关联提交

- 实现与本 evidence：`1722afeec4e809907b93c59b155421c41fe3c120`。
- SHA 回填：`c84b9fb8259cd0bbc18887c5d636a91c4a5132aa`。

## 2026-07-23 显示美化补充

- Linear 重读：`RAY-84` 由本补充从 `In Review` 进入 `In Progress`；关联 `RAY-110` 仍为 `Backlog` 且被 `RAY-105` 阻塞，本轮未改动其状态或实现。
- 实现文件：`client/app/heatmap_display.py` 新增 `HeatmapDisplayConfig`（默认启用、3 帧、Hampel 3.5×1.4826×MAD、非零 P99 的 8%、1–2 像素小岛清理、gamma 0.75、Gaussian sigma 0.9）和 `HeatmapDisplayRefiner`。它仅复制并处理 `DisplayFrame.relative_heatmap`，自身持有最多三帧的显示缓存。
- Qt 接入：`client/app/heatmap.py` 只在 `HeatmapWidget.set_display_frame` 中生成新的 `rendered_heatmap`；原始 `DisplayFrame` 仍用于 COP、轨迹和文字指标。`enabled=False` 可复现原始显示矩阵，用于视觉调参与回归比对。
- 安全边界：不会写入原始帧、可靠分段、本地分析结果、COP、左右/总载荷或报告对象；高斯结果按清理后的真实接触 mask 裁剪，不扩张足印轮廓；不会应用脚形模板。

### 逐项自动验证

```bash
UV_OFFLINE=1 \
UV_CACHE_DIR=/private/tmp/feetforceplate-uv-cache \
FEETFORCEPLATE_VENV=/private/tmp/feetforceplate-subtask-b-venv \
QT_QPA_PLATFORM=offscreen \
./scripts/local-env.sh python -m pytest \
  client/tests/test_heatmap_display_refiner.py \
  client/tests/test_ray_84_display_model.py \
  client/tests/test_ray_84_qt.py \
  client/tests/test_ray_84_controller.py -q \
  --junitxml=docs/evidence/linear/RAY-84/pytest-heatmap-refinement.xml
```

- 结果：`16 passed in 1.84s`；JUnit：[pytest-heatmap-refinement.xml](pytest-heatmap-refinement.xml)。
- 覆盖：单个异常高点会被替换且不会扩散；内部单像素低点被填补；2×2 高压簇保留；空当前帧清空显示历史而不产生伪足印；输入矩阵不可变；3 帧时间中值移除瞬时 3×3 噪声；开关不改变 `DisplayFrame` 源矩阵或 COP/左右/总载荷；连续 24 帧、高 DPI Qt render 保持有限值和 [0,1] 边界。
- 对比工件：[before](heatmap-refinement-before.png) / [after](heatmap-refinement-after.png)，由 `scripts/capture_heatmap_refinement.py` 的确定性 fixture 生成；前图包含孤立亮点和内部小孔，后图移除/填补它们。该 fixture 只用于视觉回归，不是运行时脚形模板。
- `git diff --check`（本补充文件）：通过。
- 全量客户端回归：`client/tests` 结果为 `131 passed, 1 failed`；唯一失败是范围外的 `client/tests/test_ray_114_startup_ui.py::test_failure_has_plain_copy_one_primary_recovery_and_safe_exit`，期望启动验证窗口的重试按钮取得焦点但实际未取得。单项复跑仍失败；本轮未修改 RAY-114/启动验证文件。

### 自动、真机与人工边界（补充）

- 已完成：fixture、Qt offscreen 和高 DPI 栅格自检；这是显示副本处理，不改变物理数据或任何报告结论。
- 尚未完成：真机 DO-P4864→UI latest-frame 桥接端到端、真实脚印观感、12 Hz 实时节律、Windows 目标显示器/缩放及操作员人工验收。完成前保持 `In Review`，不得标 `Done`。
