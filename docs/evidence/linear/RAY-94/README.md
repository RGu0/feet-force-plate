# RAY-94 Evidence — 报告内专业参数与原始曲线呈现

- Issue: RAY-94
- URL: https://linear.app/ray-app/issue/RAY-94/报告内专业参数与原始曲线呈现
- 抓取时间: 2026-07-20T08:56:11Z
- 当时状态: Backlog；2026-07-20T09:14:15Z 启动后为 In Progress
- 里程碑: P4：完整报告
- 优先级: Medium
- 当前状态: In Review
- 关联实现 commit SHA: `7b8ebb0ba90fbda6b062ffd845528986c37c2c73`

## 验收条目快照

- [ ] 热力图、COP 轨迹、压力-时间/分区曲线按已验证能力展示
- [ ] 参数附单位、简短定义和必要参考说明
- [ ] 图表支持左右对比和关键事件标注，但不暴露内部调试控件
- [ ] 未达到能力门槛的参数不展示
- [ ] UI/报告中区分采集约 12 Hz 与显示刷新率
- [ ] 适合 PDF 和打印的灰阶/色彩可读性
- [ ] 体育等专业人士可基于同一报告做辅助分析

## 实现文件与关键决策

- 实现：`cloud/analysis/models.py`、`cloud/analysis/features.py`、`cloud/reporting/models.py`、`cloud/reporting/builder.py`、`cloud/reporting/pdf.py`。
- 测试：`tests/cloud/reporting/test_professional_figures.py`，并回归 analysis/reporting 测试。
- 实现范围为云端结构化曲线/图表报告模型与 PDF 工件呈现，不修改客户端 UI。
- 热力图、总载荷、左右/前后分区和 COP 图表均由批准 metric ID 驱动；未批准能力不生成对应参数或曲线。
- 客户报告不包含内部质量明细、“数据可信度与限制”、失败堆栈或调试曲线。

## 验证命令与逐项结果

- `python3 -m unittest tests.cloud.reporting.test_professional_figures -v`
  - RED：4 个测试因 FeatureSet 尚无平均传感点矩阵而报错，1 个测试因曲线尚未生成而失败。
- `python3 -m unittest tests.cloud.reporting.test_professional_figures tests.cloud.reporting.test_reporting -v`
  - GREEN：13 个专业图表与统一报告测试全部通过。
- `python3 -m unittest discover -s tests/cloud/analysis -v`
  - 回归：29 个 analysis 测试全部通过。
- `python3 -m unittest discover -s tests/cloud/reporting -v`
  - 回归：13 个 reporting 测试全部通过。
- `python3 -m compileall -q cloud/analysis cloud/reporting tests/cloud/analysis tests/cloud/reporting`
  - 结果：exit 0。
- `git diff --check`
  - 结果：exit 0，无空白错误。
- Task D 最终范围验证：analysis 29、reporting 13、observability 16、migration 4，共 62 个测试通过；根目录默认 discovery 因基线没有根测试发现入口而得到 0 tests，未作为通过证据。

## 自动测试、真机与人工验证边界

- 自动测试计划覆盖曲线白名单、采样率标签、单位/定义、门控隐藏和报告模式隐私扫描。
- 灰阶/色彩可读性、中文字体、分页和打印一致性需要人工视觉与物理打印检查；完成前不应标记 Done。

## 失败或限制

- 当前没有批准的真实专业曲线白名单或视觉基准样张；默认目录仍为 DRAFT，测试使用显式批准 fixture 验证发布契约。
- 自动检查只证明图表模式具有文字替代、线型和标记，不证明实际灰阶/色彩、分页或物理打印可读性。
- evidence 不保存未脱敏客户曲线或内部调试图。
