# DO-P4864：原始数据到有效压力数据的方法 v1

## 目的与适用范围

本文定义 DO-P4864 在硬件层把已解码的原始阵列计数转换为**可追溯的 V1 初筛力学信息**的方法。它属于设备规格与硬件适配器，不属于算法层；算法层不应知道 ADC 位宽、阵列尺寸、间距、零校正、坏点修复或拟合曲线细节。

当前可配置实现见 [设备规格 1.0](device-specifications/do-p4864/1.0.json)，运行时由 `CalibratedArrayAdapter` 读取。输入原始帧不可改写；所有派生数组与质量标志同帧保存。

## 固定的设备信息

| 项 | 当前配置 | 状态 |
| --- | --- | --- |
| 已解码阵列 | 48 行 × 64 列、3072 个 `uint8` 计数 | 真机重复采集 |
| 流中排序 | 先第 1 列的 48 行，再第 2 列；列主序 | 四方向人工压测 |
| 板面原点及坐标 | 首个点为左上 `(0,0) mm`；右为 `+X`、下为 `+Y` | 用户确认 |
| 点间距 | X/Y 均 `7.99 mm` | 用户实测 |
| 感应区外形 | 约 `509.3 × 381.3 mm`（宽 × 高） | 用户实测 |
| ADC 恢复 | 8-bit、`Vref = 4.096 V`、无符号直二进制 | 当前设备配置 |
| 空载基线 | 最短 5 秒、逐点中位数零偏与 MAD 噪声 | 已实现 |
| checksum | 仅观察性质量标志，不作硬丢帧条件 | 真机实测：历史公式（`docs/通信接口设计文档.md` 5.3）对本设备完全不适用——连续 12,510 帧（600 s 采集 12,400 帧 + 基线 110 帧）不匹配率 100.0%。帧完整性实际由结构判据保障：同批实测 `length_failures`、`function_failures` 全程为 0，8 次失败均为 `TAIL` 且由邻帧重建成功（证据：`.project-context/evidence/ray-99/lossy-network-acceptance/acceptance/`，2026-08-14） |

板面坐标不是 ML/AP 身体坐标。受试者朝向和板面安装方向的变换必须在设备部署/姿态配置层显式声明，不能由本换算过程猜测。

## 每帧转换流程

```text
immutable raw_count[i]
  → persistent bad-cell assessment / isolated-cell repair in a separate matrix
  → raw_voltage[i] = raw_count[i] / 255 × 4.096
  → zero_corrected_count[i] = repaired_count[i] - median_unloaded_count[i]
  → ΔV[i] = max(zero_corrected_count[i], 0) / 255 × 4.096
  → estimated_force_n[i] = fitted_curve(ΔV[i])
  → estimated_pressure[i] = estimated_force_n[i] / (π × 3² mm²)
  → bilinear pressure interpolation + board-coordinate integration
  → provisional total force / mass-equivalent for calibration verification
```

活动点使用逐点阈值 `max(1 count, 3 × baseline MAD)` 判断。低于阈值的点在积分网格中为零压边界；该规则只用于校准积分，并不删除或覆盖原始计数。

若 `ΔV <= 0`，逐点估计力为 `0 N`；若 `ΔV >= 4.096 V`，该点为饱和/无效，估计力为 `null`，并带 `ADC_OR_FORCE_MODEL_SATURATED` 质量标志。原始值、零校正值和相对载荷仍可用于诊断。

## 首版统一电压—力曲线

令 `u = ln(ΔV / (4.096 - ΔV))`，其中 `0 < ΔV < 4.096`，逐点候选法向力为：

```text
F_point_N = exp(
  -0.416054290108397
  + exp(-2.057009203457983) × min(u, -0.6755514186685658)
  + exp(-0.5532326211611178) × max(u + 0.6755514186685658, 0)
)
```

这是一条连续、单调的双斜率曲线；斜率过渡点为 `ΔV = 1.381 V`，不是不可测阈值。其参数和验证状态已经固定在设备规格的 `force_calibration` 中，模型标识为 `voltage-to-force/two-slope-monotonic/1`。

参数由两组不同接触面积的 4.5–8.0 kg 砝码共同拟合。按“每次留出一档、其余十档重新拟合”的统一评估，合并 MAE 为 `4.690%`，优于固定 V0 幂律（`7.362%`）、自由 V0 幂律（`6.745%`）和 Hill 曲线（`7.460%`）。真人 69.8 kg 双脚重放为 68.793 kg（−1.443%），单脚为 56.791 kg（−18.638%）；真人数据没有用于拟合或选曲。

## 压力、空间积分与输出边界

为使不同接触面积的砝码可共同校准，积分不以固定受力半径估计总重，而是汇总全部响应点的候选载荷。单点暂按直径 6 mm 圆形，面积为 `π × 3² mm²`，得到候选离散压强（N/mm²；换算为 kPa 时乘 1000）；再做双线性插值并在 7.99 mm 网格上积分。

这个量是 V1 初筛的**估计力**，不等价于临床或计量认证 Pa/绝对力：点有效面积、传感器间增益、非线性、迟滞、温漂和跨区域一致性仍需要后续验证。因此硬件层输出 `estimated_force_n`、原始分段引用、零校正/修复数组和质量信息，供所有后续筛查算法按版本使用。

## 质量、版本与后续校准

每次采集必须携带设备规格版本、基线窗口标识、曲线 profile 版本、坐标/几何版本以及质量标志。V1 使用 `MVP_SCREENING_ESTIMATED_V1` 与 `ESTIMATED_FORCE_V1` 明确其产品定位。后续仍需进行固定治具多档重复加载/卸载、多个板面区域、独立留出载荷、温度/预热/漂移和跨设备复现；这些工作会形成下一版设备规格，不阻断当前初筛链路。

## 坏点修复与整项有效性

坏点审核属于硬件层，不交给算法层兜底。V1 仅允许至多 2 个持续坏点，且坏点之间不得
八邻域相邻；每个坏点必须位于板内并拥有 4 个有效正交邻点。修复值为该帧 4 个正交
邻点的均值，写入独立的 `repaired_count` 和 `repaired_cell_mask`，永不覆盖不可变原始帧。

超过数量、成片相邻、边缘无法修复、基线 MAD 超出策略、饱和或任一点力学转换失败时，
整项采集为 `INVALID`：删除暂存数据，不创建正式本地会话，也不交给网络或算法层。只有
`VALID` 会话才保存原始加密分段、加密派生观测和 SQLite 索引。

砝码原始采集、流程记录、拟合脚本和图表的证据索引在 [RAY-117 evidence](../evidence/linear/RAY-117/README.md)。
