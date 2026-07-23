# 首版候选力算法实现说明

| 项目 | 内容 |
|---|---|
| 输入模式 | `physical-sensor-observation/1.0` |
| 使用路径 | `PROVISIONAL_RESEARCH` |
| 当前设备 | DO-P4864 观察型紧凑 8-bit 帧 |
| 结果语义 | `provisional_force_n`；不是已验证 `normal_force_n` |

## 1. 当前可执行的数据转换

真机已观察到的帧为 `FF AA | 0C 07 | 01 | 3072 bytes | candidate checksum | FA`，总计 3079 B。3072 个字节对应 48×64 个 `uint8` 感应点。长度与 CheckSum 仍作为观察质量信息；当前 CheckSum 不能作为硬过滤条件，避免因未证实的覆盖范围丢弃原始数据。

空间重排以四方向实测为准，不采用旧 PDF 的行主序描述：串行第 1–48 个值为第 1 列从第 1 行到第 48 行，接着是第 2 列。因此：

```python
grid_48_rows_64_columns = payload.reshape((48, 64), order="F")
```

`grid[row, column]` 的板面坐标为：

```text
x_mm = column * 7.99
y_mm = row * 7.99
```

首点为左上角 `(0, 0)`，向右为 +X、向下为 +Y。该坐标仅为压力板物理坐标；它不是人体左/右（ML）或前/后（AP）坐标。

## 2. 空载基线与候选力

每次采集应先取得不少于 5 秒的空载帧。每点以中位数建立 `zero_median`，以 MAD 建立噪声，活动阈值为 `max(1 count, 3 * MAD)`。原始帧始终原样保留；基线只生成派生字段。

对每点原始计数 `r`，首版模型执行：

```text
raw_voltage = r / 255 * 4.096
ΔV = max(r - zero_median, 0) / 255 * 4.096
```

当 `ΔV <= 0` 时，`provisional_force_n = 0`。当 `0 < ΔV < 4.096` 时：

```text
u = ln(ΔV / (4.096 - ΔV))
F = exp(
  -0.416054290108397
  + exp(-2.057009203457983) * min(u, -0.6755514186685658)
  + exp(-0.5532326211611178) * max(u + 0.6755514186685658, 0)
)
```

当 `ΔV >= 4.096` 时，力值为 `null` 且标记 `saturation`，算法不得把它当作零值、最大值或通过插值无痕补齐。力模型 ID 为 `voltage-to-force/two-slope-monotonic/1`，当前 profile 为 `do-p4864-voltage-force/provisional-unified-known-weight-v1-20260722`。

这组参数来自不同接触面积的 4.5–8.0 kg 已知载荷试验，在该试验范围内统一双斜率模型留一误差 MAE 为 4.690%。它是首版工程转换依据，不是跨板面、跨设备或人体动作的完整标定声明。

## 3. 算法开发管线

```text
观测载荷
  → 模式/版本/质量校验
  → 选择 provisional_force_n
  → 关联阶段清单
  → 按真实主机单调时间计算
  → 板面 COP / 接触面积 / 分布特征
  → 显式部署姿态变换为 ML/AP
  → 阶段内统计、图形和研究特征集
```

每帧总候选力和板面 COP 可按如下方式计算；`F_i` 为非空且未排除点的候选力：

```text
F_total = Σ F_i
COP_x = Σ(F_i * x_i) / F_total
COP_y = Σ(F_i * y_i) / F_total
```

`F_total` 低于预先声明的最小载荷、存在饱和点、连续帧间隔异常或基线质量不合格时，必须输出缺失/降级质量结果，不能生成看似连续的 COP。速度、轨迹长度、RMS、范围和椭圆均使用真实的主机单调时间；不得假定固定帧率。真机观察到的典型到达频率约 20.7 Hz，但这是观测结果而非算法的固定采样假设。

## 4. 身体坐标与阶段

算法通过采集工作流提供的 `StageManifest` 获得受试者面向、前脚和阶段起止。它以显式、版本化的 `DeploymentTransform` 把板面 `(x, y)` 映射为身体 `(ML, AP)`。不得依据某次测试中压力峰的位置自动猜测朝向，也不得把“板面向右”直接解释为“人体向右”。

开发期可以在每个阶段计算下列候选特征：

- 总候选力、有效接触比例、饱和/缺失比例；
- 板面及 ML/AP COP 平均位置、轨迹长度、速度、范围、RMS、P5–P95；
- 95% 轨迹椭圆、左右/前后载荷分布和阶段差异；
- 帧率、时间间隔、基线噪声和异常帧计数。

这些字段是研究特征，不是临床阈值，也不得自行赋予低/中/高风险含义。

## 5. 输出与硬门控

首版运行输出必须使用独立类型，例如：

```json
{
  "analysis_run_kind": "PROVISIONAL_RESEARCH",
  "input_conformance": "PROVISIONAL",
  "force_field": "provisional_force_n",
  "publication_allowed": false,
  "screening_conclusion_allowed": false
}
```

以下情况一律拒绝或降级：模式不是观测模式、原始/派生摘要不一致、未知设备/模型版本、缺少空载基线、阶段区间重叠或超出采集时间、未声明部署姿态、饱和点超过分析策略允许的范围，或质量标记表示数据不可用。

若调用方请求正式评分、风险等级或对外报告，`PROVISIONAL_RESEARCH` 必须直接拒绝，并提示使用经过验证的 `physical-pressure-session/1.0`。这是一项产品和科学边界，不是对当前首版算法能力的否定。
