# RAY-95 Evidence — 统一报告：基础版、完整版、PDF 与打印

- Issue: RAY-95
- URL: https://linear.app/ray-app/issue/RAY-95/统一报告基础版完整版pdf-与打印
- 抓取时间: 2026-07-22T06:56:00Z
- 当时状态: In Progress
- 里程碑: P4：完整报告
- 优先级: Urgent

## 验收条目快照

- [x] 复用同一 `report_id` 追加不可变 `CLOUD_COMPLETE` 版本
- [x] PDF 工件写入哈希对象键并验证内容哈希
- [x] 同一 `source_analysis_run_id` 幂等发布
- [x] 客户文档只输出一个综合指数及安全提示、物理专业参数和曲线
- [x] 问卷标签、私有 reason code、质量/调试字段不进入客户文档
- [ ] 嵌入字体、稳定分页、灰阶/彩色打印人工检查
- [ ] 真实参考工件、硬件适配器、操作员和临床验证

## 实现文件与关键决策

- `cloud/reporting/static_balance.py`
- `tests/cloud/reporting/test_static_balance_reporting.py`
- `StaticBalanceCloudReportService` 复用现有基础报告记录，按源分析运行追加版本，不覆盖历史版本。
- `StaticBalanceReportBuilder` 将 V1 综合指数作为唯一核心评分，专业区展示四阶段 COP/速度/椭圆参数与时间曲线；客户公开数据不含内部规则追踪和敏感问卷。
- 仍使用现有最小 PDF 参考渲染器，明确其仅为自动契约测试实现，不能替代正式字体和打印验收。

## 验证命令和结果

- `./scripts/local-env.sh python -m pytest tests/cloud/reporting/test_static_balance_reporting.py -q` — `3 passed`
- `./scripts/local-env.sh python -m pytest tests/cloud -q` — `101 passed, 9 subtests passed`
- 自动检查覆盖 report_id、版本号、PDF SHA-256、幂等和隐私拒绝词；未使用真实客户或药物数据。

## 自动测试/真机/人工边界

- 自动：合成标准物理会话和规则结果。
- 真机/人工：RAY-117 输入、字体/分页/打印、灰阶曲线、参考工件、操作员一致性和临床验证未完成。
- 因此 issue 完成自动切片后应进入 In Review，不能标 Done。

## 关联 commit

- `11a21a7`
