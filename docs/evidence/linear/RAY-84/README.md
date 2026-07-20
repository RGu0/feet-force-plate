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
