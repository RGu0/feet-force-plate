# DO-P4864 四段真机回放测试夹具（v1）

这是项目根目录 `tests` 下的**规范测试输入**。它保存了一次完整、已去标识化的
DO-P4864 真机采集结果，供后续 UI、工作流、显示链路和算法回归优先回放；只有需要
验证连接、串口吞吐、设备异常或新硬件版本时，才需要重新连接真机。

## 覆盖的四段测试

| ID | 站位 | 请求时长 | 已保存有效帧 |
| --- | --- | ---: | ---: |
| `open_eyes_bilateral` | 并足双脚站立、睁眼 | 20 秒 | 414 |
| `closed_eyes_bilateral` | 并足双脚站立、闭眼 | 20 秒 | 415 |
| `tandem_left_front` | 串联站立、左脚在前、右脚在后 | 20 秒 | 414 |
| `tandem_right_front` | 串联站立、右脚在前、左脚在后 | 20 秒 | 415 |

总计 1,658 帧。实际采集的单段耗时为 20.0749--20.0946 秒；左脚在前一段曾出现
1 个无效候选帧，解析器重同步后未将其纳入本夹具。

## 文件格式与完整性

- `reference-poses.npz`：仅包含四段相对 `uint8`、48×64 矩阵序列；
- `metadata.json`：帧数、采样间隔、去标识化范围和 SHA-256；
- SHA-256：`2495b910bbf7e4fcca0cd0db36dde809f0fd6395bb6060eded44db575acd6f90`；
- 名义帧间隔：50 ms（仅供工程回放定时，不表示已完成设备采样率认证）。

原始串口字节、时间戳、源帧索引、绝对幅值、操作者和设备标识均未进入仓库。
旧的 `client/tests/fixtures/dop4864_reference_protocol_v1/` 保留为兼容副本；新的
测试必须从本目录读取，且两份内容由 SHA-256 约束为相同版本。

## 使用边界

这是工程回放夹具，不是校准压力记录、临床数据集或客户报告输入。它可以验证数据
处理与界面对同一确定性输入的行为，但不能替代真机端到端、临床范式、物理尺寸、
标定或人工可用性验收。

运行夹具合同与生产显示投影回放：

```bash
UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/feetforceplate-uv-cache \
FEETFORCEPLATE_VENV=/private/tmp/feetforceplate-subtask-b-venv \
./scripts/local-env.sh python -m pytest \
  client/tests/test_ray_91_reference_protocol_fixture.py -q
```
