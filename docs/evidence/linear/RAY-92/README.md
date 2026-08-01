# RAY-92 Evidence

- Issue：`RAY-92` 受试者标识、选填档案与简短授权
- URL：https://linear.app/ray-app/issue/RAY-92/受试者标识选填档案与简短授权
- 复核与本机闭环时间：2026-07-31
- 当前 Linear 状态：Done（2026-07-31T16:01:19Z 写入并回读确认）
- 里程碑：P2：一键筛查
- 优先级：High
- 功能验收结论：Linear 原始 10 条均已有本地真实组件或真实入口 evidence；已标记 Done
- Linear evidence：10/10 条已勾选；验证 summary 与报告预览截图共 2 个附件；closeout 评论已回读

## Linear 原始 10 条验收矩阵

| # | Linear 验收条目 | 结论 | 可复现 evidence |
|---|---|---|---|
| 1 | 支持档案号、病历号、体检号、住户编号等 `institution_external_id` | 通过 | `ExternalIdType` 四类枚举、P-02 四类选择器；`test_subject_page_exposes_id_types_and_lookup_action` |
| 2 | 编号仅在本机构范围查找、去重和关联历史 | 通过 | `LocalReplayStore` 使用 `tenant + issuer + id_type + HMAC` 唯一索引；会话以 `subject_uuid` 关联；`test_local_identifier_index_is_hmac_and_isolated_by_tenant_issuer_and_type`、`test_session_creation_receives_selected_subject_and_consent_snapshot` |
| 3 | 支持无机构编号的非实名快速建档 | 通过 | 真实加密 SQLite 可创建无外部编号档案；`test_anonymous_quick_create_uses_unknown_profile_without_identity`、`test_local_replay_store_encrypts_updated_profile_fields` |
| 4 | 姓名、身份证和联系方式不必填；首版不要求身份证 | 通过 | `IdentityInput` 全部可空，匿名/机构编号路径均不要求身份字段；匿名建档测试断言 `identity is None` |
| 5 | 年龄、性别、身高、体重、基础病和既往损伤选填 | 通过 | `AnalysisProfile` 六项均为 `OptionalField`，P-03 支持保存或跳过；控制器和加密持久化测试覆盖 |
| 6 | 每个选填字段区分已填写、明确无、未知、拒绝提供、不适用 | 通过 | 五态 `FieldState` 贯穿 DTO、P-03、控制器和加密 payload；`test_profile_fields_each_have_an_explicit_missing_state_selector`、`test_optional_field_preserves_missing_meaning` |
| 7 | 首次建档完成简短授权；相同用途后续测试复用 | 通过 | P-04 首次明确确认；真实 SQLite 按租户、受试者、策略/用途/字段精确复用；`test_matching_valid_consent_is_reused_without_creating_a_new_record`、`test_local_consent_reuse_requires_the_same_tenant_and_policy_scope` |
| 8 | 用途、字段或规则实质变化时重新确认 | 通过 | 不匹配 policy version、purpose 或 data categories 时返回 `CONFIRMATION_REQUIRED`；新授权追加而非覆盖旧记录；相关策略测试及 `test_local_consent_reconfirmation_preserves_prior_receipt` |
| 9 | 档案冲突不自动合并，由机构人员确认 | 通过 | 工作流 `CONFLICT` 不选择候选；真实 SQLite 重复创建原子回滚并返回“由机构人员确认”；`test_duplicate_local_identifier_is_not_auto_merged_or_partially_created` |
| 10 | 访问和导出按机构隔离并留审计记录 | 通过 | 本地真实 `AuditPort` 校验 subject tenant 后追加双信封加密事件；报告预览导出完成后记录版本化报告引用；真实四阶段入口 evidence 含 1 条加密 `SUBJECT_EXPORT` |

## 本轮补齐的真实适配器缺口

旧 evidence 只证明端口编排，并明确承认 Subject/Consent/Audit 真实适配器未完成。本轮对真实 `LocalReplayStore` 和真实 `main.py --replay --verify` 入口补齐：

- 授权查询不再忽略 `tenant_id` 和 policy；只复用相同租户、受试者、规则版本、必要用途及数据字段范围的授权。
- 授权记录改为按 `consent_record_id` 追加保存，重新确认不会覆盖旧证据；旧单记录表自动迁移并保留可复用授权。
- 授权创建先验证受试者属于同一租户，跨租户写入被拒绝。
- 重复机构编号的受试者创建在一个 SQLite 事务内原子失败，不自动合并，也不会留下半条档案。
- 新增追加式 `subject_audit_events`；访问与报告导出的明细 payload 使用双信封加密，跨租户写入被拒绝。
- `local_entry.py` 使用真实 store 作为 AuditPort，移除 no-op audit。
- 修复 `ReportConnectedController` 的报告预览导出分支绕过基类审计的问题；只有 PDF 导出成功后才记录报告 ID 与版本。
- 本机验证 summary 现在会拒绝“未产生唯一导出审计”或“审计 payload 含明文报告 ID”的运行。

## TDD 证据

本轮新增行为均先观察到预期失败，再做最小实现：

- 授权租户/策略隔离、历史保留和跨租户创建：3 failed → 3 passed。
- 访问/导出加密审计和跨租户拒绝：2 failed（方法缺失）→ 2 passed。
- 重复机构编号：失败为裸 `sqlite3.IntegrityError` → 原子拒绝测试通过。
- 四阶段入口导出审计：失败为审计表 0 条 → 1 passed，表内为 1 条 `SUBJECT_EXPORT`。
- 旧授权迁移做 mutation RED：断开迁移后因缺少 tenant 列失败；恢复后 1 passed。
- 本机 evidence summary：缺少 `subject_audit` 时失败；接入真实 AuditPort 后 1 passed。
- 同版本删除非科研用途：旧逻辑错误返回 `REUSED` → 用途集合精确匹配后返回 `CONFIRMATION_REQUIRED`；额外科研用途仍可独立选择。

## 新鲜验证

### RAY-92 聚焦回归

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest \
  client/tests/test_ray_92_participant.py \
  client/tests/test_ray_92_consent.py \
  client/tests/test_ray_92_controller.py \
  client/tests/test_ray_92_qt.py \
  client/tests/test_ray_92_session_binding.py \
  client/tests/test_local_replay_store.py \
  client/tests/test_v1_local_end_to_end.py \
  client/tests/test_local_mvp_validation.py \
  -q --junitxml=docs/evidence/linear/RAY-92/pytest-results.xml
```

结果：JUnit `tests=39, failures=0, errors=0, skipped=0, time=50.603s`。SHA-256：`2934da5c4e5bbcb118eb2c671a1f08c7a457d441c1288580ba4fa3ba7b62eb5e`。

### 全项目回归

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python -m pytest -q \
  --junitxml=docs/evidence/linear/RAY-92/full-pytest-results.xml
```

控制台：`602 passed, 3 warnings, 9 subtests passed in 40.33s`。JUnit：`tests=611, failures=0, errors=0, skipped=0, time=40.308s`。SHA-256：`2413c97c6a4833fd66b81a5a63803a562768df481e0f275d0844ec5595479119`。三条 warning 均为既有 `TestProtocol` 收集提示。

### 真实本机入口 evidence

```bash
QT_QPA_PLATFORM=offscreen ./scripts/local-env.sh python main.py \
  --replay --verify --replay-speed 500 \
  --output-dir docs/evidence/linear/RAY-92/local-mvp-2026-07-31
```

结果：exit 0。`summary.json` SHA-256：`01007dbc1ed2e16b67c59a05e7223ab6a90e3bb4248410ec4c5a1a7b8eb894d1`。

实际 SQLite 计数：`subjects=1`、`consents=1`、`audit=1`、`stages=4`、`reports=1`；审计事件为 `SUBJECT_EXPORT / local-replay`，加密 payload 986 bytes。summary 明确记录 `encrypted_payload=true`、`export_event_count=1`。

工件：

- [`local-mvp-2026-07-31/summary.json`](local-mvp-2026-07-31/summary.json)
- [`local-mvp-2026-07-31/report.pdf`](local-mvp-2026-07-31/report.pdf)
- `01-preflight.png`、四阶段页面 `02`～`05`、`06-report-preview.png`
- `local-state/local-replay.sqlite3`（本次只含合成回放标识与 fixture，不含真实受试者或原始矩阵）

### 静态与工作树检查

- `ruff check`：All checks passed。
- `git diff --check`：通过。

## 边界

- 本次关闭的是 RAY-92 的本地功能合同和可重复 evidence，不代表生产机构云端 Subject/Consent/Audit 服务已部署。
- 回放入口使用仓库固定四阶段 fixture；它不证明真实硬件、目标 Windows、高 DPI、机构法务文案、现场操作员或临床有效性。
- 上述发布门槛继续由 RAY-96、RAY-101、RAY-108 及 P2 综合现场验收追踪，不再把它们错误地算作 RAY-92 这 10 条本地功能合同的未实现项。
