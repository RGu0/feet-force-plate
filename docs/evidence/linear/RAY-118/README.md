# RAY-118 Evidence — V1 静态平衡筛查规则引擎与综合评分

- Issue: RAY-118
- URL: https://linear.app/ray-app/issue/RAY-118/v1-静态平衡筛查规则引擎与综合评分
- 抓取时间: 2026-07-22T06:52:00Z
- 当时状态: In Progress
- 里程碑: P4：完整报告
- 优先级: Urgent

## 验收条目快照

- [x] 规则优先的背景、完成度和平衡指标合并
- [x] 明确高风险背景不能被良好压力结果平均掉
- [x] 完成失败可独立形成风险证据
- [x] 未知背景与可选药物类别标签不等同于“否”
- [x] 技术校验失败单独输出 `TECHNICAL_INVALID`
- [ ] 冻结 60+ 参考工件与正式压力分位分级
- [ ] 真实硬件、操作员一致性、临床/前瞻性验证

## 实现文件与关键决策

- `cloud/analysis/risk_rules.py`
- `tests/cloud/analysis/test_risk_rules.py`
- `QuestionnaireSnapshot` 只接受年龄、二值/未知背景和枚举药物类别；不保存药名、剂量或自由文本。
- `evaluate_screening_risk` 先判断技术有效性，再分别计算背景、完成和物理指标证据，最后按最高风险合并；分数始终受风险区间上限约束。
- 当前阈值是版本化筛查原型，不代表医疗诊断或已批准临床 cut-off；冻结参考工件接入前不得发布正式压力等级。

## 验证命令和结果

- `./scripts/local-env.sh python -m pytest tests/cloud/analysis/test_risk_rules.py -q` — `5 passed`
- `./scripts/local-env.sh python -m pytest tests/cloud -q` — `98 passed, 9 subtests passed`
- 自动测试使用合成标准物理输入；未包含真实客户数据、药物明细或敏感信息。

## 自动测试/真机/人工边界

- 自动：覆盖高风险背景优先、完成失败、未知语义、药物类别最小化和分数上限。
- 真机/人工：RAY-117 物理输入、冻结参考人群、操作员一致性、PDF/打印和临床验证仍未完成。
- 因此本 issue 保持 In Progress，后续完成自动实现后应进入 In Review，不得直接标 Done。

## 失败或限制

- 当前四阶段特征阈值为安全筛查原型，未声称临床诊断能力。
- 参考工件缺失时不能生成正式压力领域等级；规则引擎仍可对明确背景或动作完成失败给出安全提示。

## 关联 commit

- `606a56a`
