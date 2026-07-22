# 标准物理输入契约

| 项目 | 内容 |
|---|---|
| 契约 ID | `physical-pressure-session` |
| 契约版本 | `1.0` |
| 使用方 | 静态平衡特征管线、评分规则和报告生成 |
| 生产方 | 各硬件型号对应的采集、标定和物理换算层 |
| 核心原则 | 算法不读取串口帧、ADC/计数值、行列顺序或设备专用标定参数 |
| Linear 实施任务 | [RAY-117：硬件标准化层](https://linear.app/ray-app/issue/RAY-117/硬件标准化层任意传感器阵列到统一物理输入) |

> **实施边界（2026-07-22）**：本文件的 `physical-pressure-session/1.0` 是下游、身体语义和绝对物理量已经验证后的契约，不是当前 RAY-117 的直接输出。RAY-117 首先交付上游 `physical-array-session/1.0`：板面坐标、不可变原始计数、5 秒空载窗口得出的零点/噪声参考、相对载荷、主机单调时间、质量与版本。未验证已知载荷标定、有效面积或板面到身体方向时，绝不写成 N、Pa、ML/AP 或 COP。

## 0. 上游物理阵列契约

```text
decoded immutable sensor array
  → board geometry + raw_count
  → qualifying 5-second unloaded baseline
  → zero_corrected_count + relative_load_count
  → physical-array-session/1.0
  → later verified coordinate/force semantic adapter
  → physical-pressure-session/1.0
```

`physical-array-session/1.0` 坐标系为 `BOARD_TOP_LEFT_X_RIGHT_Y_DOWN`。当前 DO-P4864 的用户确认约定为：左上第一个点 `(0, 0) mm`，x 向右、y 向下，48×64 网格，两个方向的点间距均为 `7.99 mm`；源索引是列主序 `column × 48 + row`。供应商图中的 6×6 mm 和 7×7 mm 仅是名义来源数据，电学有效面积仍未验证。

5 秒空载只产生逐点 `zero_offset_count` 与 `noise_mad_count`。当前帧保留 `raw_count`，并分别输出有符号 `zero_corrected_count = raw - zero_offset` 和非负 `relative_load_count = max(zero_corrected, 0)`；不覆盖原始值。`normal_force_n` 仅在已知载荷曲线和不确定性已验证时才可出现，否则为 `null` 且质量状态为降级。

## 1. 责任边界

后续已验证的语义适配层负责把 RAY-117 上游契约转换为本契约：

```text
physical-array-session/1.0
  → 已验证的已知载荷标定、有效面积和安装方向
  → 板面到身体 ML/AP 坐标换算
  → 真实物理坐标和真实法向力（仅在证据充分时）
  → physical-pressure-session/1.0
```

核心算法只接收契约输出：

```text
physical-pressure-session/1.0
  → ML/AP 压力中心轨迹
  → 位移、速度、范围、面积和阶段差异
  → 风险规则、综合评分和报告
```

更换传感器阵列时，只新增或修改硬件适配器；静态平衡算法、评分规则和报告字段不因设备行列数、感应点尺寸或通信协议改变。

## 2. 统一坐标和单位

标准输入必须使用受试者身体坐标系：

| 字段 | 规定 |
|---|---|
| `ml_mm` | 左右轴，单位 mm；向受试者右侧为正 |
| `ap_mm` | 前后轴，单位 mm；向受试者前方为正 |
| `normal_force_n` | 单个感应点在该帧的法向力，单位 N |
| `active_area_mm2` | 单个感应点的有效感应面积，单位 mm² |
| `timestamp_s` | 会话单调时间，单位 s；必须严格递增 |

后续经过验证的坐标语义适配层必须完成板面坐标到身体 ML/AP 坐标的转换。受试者正站、固定左转 90°以及左右脚在前时，算法看到的坐标语义始终不变；RAY-117 的板面物理层不推断这些语义。

感应点可以来自规则矩阵，也可以是不等距或非矩形布局。算法按 `cell_id + ml_mm + ap_mm` 处理，不依据行号、列号或数组内存顺序推断物理位置。

## 3. 会话结构

```json
{
  "schema_version": "physical-pressure-session/1.0",
  "session_id": "uuid",
  "coordinate_frame": "SUBJECT_ML_AP",
  "coordinate_unit": "mm",
  "force_unit": "N",
  "measurement_profile": {
    "profile_version": "string",
    "physical_validation": "VALIDATED",
    "timing_validation": "VALIDATED",
    "coordinate_validation": "VALIDATED",
    "uncertainty_profile_version": "string"
  },
  "cells": [
    {
      "cell_id": "string",
      "ml_mm": 0.0,
      "ap_mm": 0.0,
      "active_area_mm2": 25.0,
      "status": "ACTIVE"
    }
  ],
  "stages": [
    {
      "stage_id": "BIPEDAL_EO",
      "start_s": 0.0,
      "end_s": 20.0,
      "completion_status": "COMPLETED"
    }
  ],
  "frames": [
    {
      "timestamp_s": 0.0,
      "normal_force_n": [0.0],
      "quality": "VALID"
    }
  ]
}
```

JSON 仅用于说明字段语义；正式传输和存储可以采用更高效的二进制或列式格式，但语义必须一致并受 `schema_version` 约束。

`stages` 中的阶段边界、动作完成状态和前脚信息由测试工作流产生，标准输入组装器只做版本化透传；硬件适配器不得推断、改写或替代客户端动作状态机。RAY-117 硬件适配器只负责板面物理帧、实际时间和测量质量；身体坐标属于后续语义适配层。

## 4. 必填信息

### 4.1 固定感应点表

每个会话必须提供一份不可变的感应点表：

- `cell_id` 在会话内唯一且顺序稳定；
- `ml_mm / ap_mm` 是感应点有效区域中心的真实身体坐标；
- `active_area_mm2 > 0`；
- `status` 至少支持 `ACTIVE / EXCLUDED`；
- 每帧 `normal_force_n` 数量和顺序必须与感应点表完全一致。

### 4.2 实际时间轴

- 使用实际采样时间，不根据名义采样率伪造等间隔时间；
- `timestamp_s` 严格递增；
- 阶段边界与帧使用同一个单调时间域；
- 丢帧、长间隔和时钟异常在进入算法前形成标准质量标志。

### 4.3 物理有效性

进入正式评分的输入必须同时满足：

```text
physical_validation   = VALIDATED
timing_validation     = VALIDATED
coordinate_validation = VALIDATED
```

算法不接收“原始计数但字段名称写成 N”的数据，也不在内部猜测单位、间距、旋转方向或标定曲线。

## 5. 核心算法的统一计算

对有效感应点 `k` 和时刻 `t`：

```text
F(t)  = Σ Fk(t)
ML(t) = Σ(Fk(t) × mlk) / F(t)
AP(t) = Σ(Fk(t) × apk) / F(t)
```

其中 `Fk(t)` 为 `normal_force_n`。当总力低于版本化有效载荷阈值时，该帧不可用于压力中心计算。

相邻有效帧的速度使用真实时间差：

```text
vML(t) = ΔML / Δt
vAP(t) = ΔAP / Δt
v(t)   = sqrt(vML(t)^2 + vAP(t)^2)
```

输出单位分别为 `mm`、`mm/s`，面积指标为 `mm²`。同一组公式适用于不同点数、点距、点尺寸和阵列形状。

## 6. 能力门控

硬件无关不等于忽略测量能力。每个指标仍声明：

- 最低实际采样率和允许的最大时间间隔；
- 最短有效时长和最低有效帧比例；
- 所需物理量、坐标和时间验证等级；
- 允许的测量不确定度和坏点比例；
- 适用测试协议、特征管线和参考人群版本。

算法按标准能力字段门控，不按 `device_model` 写分支。满足同一测量一致性规范的设备应得到同一算法能力；不满足时返回 `UNSUPPORTED / DEGRADED / INVALID`，不得静默降级为正式评分。

## 7. 一致性验证

每个新硬件适配器必须通过与算法分离的契约测试：

1. 已知载荷夹具验证每点力值和总力；
2. 已知物理位置验证 ML/AP 坐标、原点、方向和旋转；
3. 已知时间序列验证时间戳、采样间隔和速度；
4. 同一标准物理 fixture 输入不同适配器后，核心特征结果在容差内一致；
5. 坏点、饱和、低载荷、缺帧和无效标定能够被明确拒绝；
6. 输出记录适配器版本、测量规范版本和输入摘要，支持历史重算。

DO-P4864 是本项目首个硬件适配器，但不是本契约或核心算法的组成部分。其串口帧、列优先映射、原始 `uint8` 和设备采样特征只存在于设备接入层及通信接口文档中。
