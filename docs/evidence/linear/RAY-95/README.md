# RAY-95 Evidence — 统一报告：基础版、完整版、PDF 与打印

- Issue: RAY-95
- URL: https://linear.app/ray-app/issue/RAY-95/统一报告基础版完整版pdf-与打印
- 抓取时间: 2026-07-20T08:56:11Z
- 当时状态: Backlog；2026-07-20T09:08:41Z 启动后为 In Progress
- 里程碑: P4：完整报告
- 优先级: Urgent
- 关联 commit SHA: 待本任务提交

## 验收条目快照

- [ ] 有效会话结束后本地生成 BASIC_READY 版本
- [ ] 云端原始数据完整且算法完成后生成 CLOUD_COMPLETE 新版本
- [ ] 报告版本不可覆盖；算法升级重算生成新 report_version
- [ ] 固定结构：筛查摘要 → 风险提示 → 核心指标 → 专业参数与曲线 → 通俗说明/建议 → 机构信息
- [ ] 使用“筛查、风险提示、建议进一步评估”等措辞，不输出确定性疾病诊断
- [ ] 内部质量详情、调试参数和失败原因不得进入客户 PDF
- [ ] 机构预览、导出 PDF 和打印
- [ ] 不提供二维码、公开链接或受试者账号领取
- [ ] 基础版升级完整后，记录端默认展示最新可交付版本且保留历史版本
- [ ] PDF 模板、字体、分页、页眉页脚和打印一致性测试

## 实现文件与关键决策

- 实现：`cloud/reporting/models.py`、`cloud/reporting/builder.py`、`cloud/reporting/pdf.py`、`cloud/reporting/service.py`。
- 数据库：`cloud/reporting/migrations/0001_reporting.sql`。
- 测试：`tests/cloud/reporting/test_reporting.py`。
- 已实现严格客户模式、统一 `report_id` 不可变版本、重算追加、PDF 工件摘要、内部 ID 对象键、对象存储端口和 `report.published.v1`。
- 本任务不实现本地 BASIC 生成或客户端预览/打印按钮，只验证云端追加 `CLOUD_COMPLETE` 时复用既有报告 ID。

## 验证命令与逐项结果

- `python3 -m unittest tests.cloud.reporting.test_reporting -v`
  - RED：因 `cloud.reporting.builder` 尚不存在而按预期失败。
  - GREEN：8 个统一报告/PDF 契约测试全部通过。
- `python3 -m unittest discover -s tests/cloud/reporting -v`
  - 回归：8 个测试全部通过，0 failure，0 error。
- `python3 -m compileall -q cloud/reporting tests/cloud/reporting`
  - 结果：exit 0。
- `git diff --check`
  - 结果：exit 0，无空白错误。
- `python3 -m unittest tests.cloud.test_migrations -v`
  - 结果：4 个 Task D 迁移契约测试通过；当前环境没有 PostgreSQL，未执行真实迁移。
- Task D 最终范围验证：analysis 29、reporting 13、observability 16、migration 4，共 62 个测试通过；根目录默认 discovery 因基线没有根测试发现入口而得到 0 tests，未作为通过证据。

## 自动测试、真机与人工验证边界

- 自动测试计划覆盖报告 ID 复用、版本不可变、重算追加、内容白名单、PDF 工件摘要和禁止诊断措辞/字段。
- 中文字体嵌入、分页、目标 Windows 打印机和物理打印一致性需要人工/外部环境验证；完成前不应标记 Done。

## 失败或限制

- 本任务不拥有本地 BASIC 报告生成与客户端打印流程；自动测试通过 seed 的 BASIC 版本验证云端复用 report_id。
- `MinimalPdfRenderer` 是无外部依赖的有效 PDF 契约渲染器，不宣称通过中文字体、300 DPI 图表、分页视觉或目标打印机验收；生产需替换为批准渲染适配器。
- evidence 不保存含身份明文的报告样本。
