# RAY-751 库一致性审计报告（只读观察）

- 性质：只读库一致性观察（kind: read-only-library-consistency-observation），审计过程未执行任何写入（writes_performed: false）。
- 观察时间（UTC）：2026-10-14T02:32:21.193297+00:00；平台：macOS。
- 源头：source_head `fe1c1eb5716eb41657697b62424992c397ce53c0`；工作树：`.worktrees/ray-751/library-consistency-audit`。
- 共享根：`project-context`（来源：`.ai-project/context-manifest.yaml` + 已解析的 `.project-context` 符号链接）；OneDrive 共享文档根：`~/Library/CloudStorage/OneDrive-Personal/Project-Doc-Sync/feet-force-plate/docs`。

## 三个文件的完整映射（Git 文档 / 共享文档 / 当前清单条目）

| 路径 | Git 文档 SHA256 / 字节 | 共享文档 SHA256 / 字节 | 当前清单条目 SHA256 / 大小 | 共享=Git | 匹配当前清单 |
|---|---|---|---|---|---|
| docs/evidence/linear/RAY-119/2026-07-30-human-plantar-frame-evidence.md | 9e58b7de7c2c1abd8cbab315b66ee453664945752737828b436e7d0b16715a58 / 4544 | 83c6af385a10cc148b4fb9b6e00694ed679db58208012f92073a1e535675eadb / 4630 | 83c6af385a10cc148b4fb9b6e00694ed679db58208012f92073a1e535675eadb / 4630 | 否 | 是 |
| docs/evidence/linear/RAY-119/2026-07-30-live-dynamic-load-attempt.md | b02c4334e9e9411798bfbd05250040374b41faa3bc6e1b4957bce051971fbdfc / 3430 | c378a1265b5ff2dfadabffaf1278dfde5f5ed06ffe8c5a3627e35c0dcb9ee356 / 3574 | c378a1265b5ff2dfadabffaf1278dfde5f5ed06ffe8c5a3627e35c0dcb9ee356 / 3574 | 否 | 是 |
| docs/evidence/linear/RAY-119/README.md | 342ffc1c68bf82d074d1fde53076c4cd26487a0f5a0d3893c0f8452059ea1b20 / 12183 | d8ff2bed7d2a8db4698b453a03c0320ec119c1490518d7d68a1e39d3a66bc3d5 / 20989 | d8ff2bed7d2a8db4698b453a03c0320ec119c1490518d7d68a1e39d3a66bc3d5 / 20989 | 否 | 是 |

差异规模：前两个文件各新增 3 行、删除 1–2 行；README 变化大得多（新增 182 行、删除 8 行，涉及 @@ -5、@@ -104,4、@@ -143,2、@@ -189、@@ -228,0 等差异块）。

## 当前共享文档与清单的一致性

- 三个共享文档的当前内容均与当前内容清单条目一致（matches_current_manifest: true）。
- 当前清单 SHA256：`4af0a82bae8466b1f4d746e9504822579814a15ce86d9ca7d65f46e03e4ed86b`。

## 历史合并范围与 Git 跟踪副本的分叉

- 三个文件的 Git 跟踪文档副本均与共享文档不一致（shared_equals_git_document: false），README 的差异尤为显著。
- 历史完成记录（R1，completed）：PR https://github.com/RGu0/feet-force-plate/pull/61，合并提交 `70bf6455f7a8694bdbd4eae4dcb017944f0403e0`，回执 `b6877117402464cda6ec5cb8c665c71fe63cf7a37ae1a8057a87089ccbc4ca39.json`。
- 历史范围清单（historical_scope_manifest）可用，引用为 `merge_commit:70bf6455f7a8694bdbd4eae4dcb017944f0403e0`；

其三条历史清单条目如下（来自本地可读取的合并提交，不是当前 Git 文档副本）：

| 路径 | 历史清单 SHA256 | 字节 |
|---|---|---|
| docs/evidence/linear/RAY-119/2026-07-30-human-plantar-frame-evidence.md | 9e58b7de7c2c1abd8cbab315b66ee453664945752737828b436e7d0b16715a58 | 4544 |
| docs/evidence/linear/RAY-119/2026-07-30-live-dynamic-load-attempt.md | b02c4334e9e9411798bfbd05250040374b41faa3bc6e1b4957bce051971fbdfc | 3430 |
| docs/evidence/linear/RAY-119/README.md | 4ecc9d43a200a887b8d227196af0c4f320651bad53481572950e0085819bdced | 20890 |

本地范围分支缺失，本次使用保留完成记录所指的本地合并提交；未推断分支缺失原因。
- 保留的 schema2 回执（`07555112f0d50baf28d642af7cce7dbdc4c7fdaf130f3e397ff0a415c94ea2ec`）记录的是一个 worktree 来源、状态为 verified identical（1554 个文件）的清单，其 SHA 与当前清单相同；而原始合并提交的清单为旧条目。两种来源身份不同：保留回执未在本次审计中重新验证（reverified_in_this_audit: false），且共享清单当前一致并不意味着 Git 文档副本为最新，也不证明历史范围回执经过重新验证。

## 行政性证据（仅限所载事实）

- 日期 2026-09-30（Asia/Shanghai）的 doc-sync 摘录（`.../doc-sync/2026-09-30.md`，SHA256 `e0c7de23f1b511fe57a7d44d5c8d5a77bf0b2c0e8c4117bc3dca66a9e2479ddc`）记录了 README 状态澄清与两份 2026-07-30 证据文件的历史性表述调整。
- 该记录及保留的 PR61/完成回执仅为行政性证据，不构成 OneDrive 编辑器/版本历史的证明，也不构成物理设备与部署验收的证据（该项未评估，仍是 RAY-119 的关卡）。
- OneDrive 编辑器与版本历史：未知/未获取。

## 明确的未知项

- OneDrive 编辑器与版本历史未知；未检索。
- 物理设备与部署验收未评估，仍为 RAY-119 关卡。
- 历史回执未在本次审计中重新验证。
- 本地范围分支缺失；合并提交清单仅在其本地存在时可读。
- 记录上述不同来源身份时不作篡改定性，也不虚构时间先后因果。

## 建议

- 若当前三个条目匹配，则不刷新或恢复当前清单。
- 保留历史范围不匹配与 doc-sync 事实；任何当前类型化复核或历史重录仅经现有关卡、且需客观需要或已批准处置后进行，绝不盲目改写旧证据。
- 不覆盖共享文档、不刷新清单、不改写回执、不宣称 RAY-119 设备验收。
- Git 文档副本的任何对账作为后续事项，须经审查后跟踪。
