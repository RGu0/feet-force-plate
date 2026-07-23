# 标准物理压力输入契约

| 项目 | 内容 |
|---|---|
| 契约 ID | `physical-pressure-session` |
| 契约版本 | `1.0` |
| 生产方 | 硬件标准化层；测试会话组装器透传阶段元数据 |
| 消费方 | 本地/云端算法层 |
| 核心原则 | 算法只读取实际物理信息，不读取设备、协议、阵列或标定细节 |
| Linear 实施任务 | [RAY-117：硬件标准化层](https://linear.app/ray-app/issue/RAY-117/硬件标准化层任意传感器阵列到统一物理输入) |

## 1. 边界

本契约是算法层的一级物理输入，而不是硬件内部的采集或标定中间数据：

```text
设备协议、原始计数、阵列行列、零偏与载荷标定
  → 硬件标准化层
  → physical-pressure-session/1.0
      每点实际板面坐标（mm）
      每点法向力（N）
      每点有效面积（已验证时）
      实际单调时间与质量
  → 算法层内部的特征与规则计算
```

COP、轨迹、速度、RMS、范围、椭圆、阶段比较、风险、评分和报告均是算法层的二级结果；它们不是本契约字段，硬件层不得计算或传递。

硬件层必须在内部保留不可变原始数据及其校准证据，但算法层不读取它们。若硬件尚不能提供经过批准的 N 语义，不能生成可被算法消费的本契约；必须以 `DEGRADED` 或 `UNSUPPORTED` 的能力结果阻断正式分析，绝不将计数或相对载荷伪装成 N 或 Pa。

## 2. 坐标、单位和感应点

`coordinate_frame` 固定为 `BOARD_TOP_LEFT_X_RIGHT_Y_DOWN`：左上角第一个感应点中心为 `(0, 0)`，X 向右为正，Y 向下为正。感应点坐标是实际板面位置；算法不得从阵列行列、标称间距或设备型号重建坐标。

当前 DO-P4864 的声明几何为：48×64、列主序源映射、首点 `(0, 0) mm`，X/Y 点间距均为 `7.99 mm`。这是该硬件配置，不是算法接口对任何阵列的假设。

| 字段 | 语义 |
|---|---|
| `board_x_mm` / `board_y_mm` | 感应点有效区域中心的实际板面坐标，单位 mm |
| `normal_force_n` | 该帧该点已验证的法向力，单位 N |
| `active_area_mm2` | 已验证的有效感应面积；未知时为 `null` |
| `timestamp_s` | 相对会话起点的实际单调时间，单位 s，严格递增 |

每个会话给出不可变的 `cells[]` 表；`cell_id` 在会话内唯一、顺序稳定。规则矩阵、不等距阵列和非规则布局均由逐点坐标表达。`status` 至少支持 `ACTIVE` 和 `EXCLUDED`；饱和是每帧质量，不是固定点状态。

## 3. 会话结构

```json
{
  "schema_version": "physical-pressure-session/1.0",
  "session_id": "uuid",
  "coordinate_frame": "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN",
  "coordinate_unit": "mm",
  "force_unit": "N",
  "area_unit": "mm2",
  "time_unit": "s",
  "measurement_profile": {
    "profile_version": "string",
    "force_validation": "VALIDATED",
    "geometry_validation": "VALIDATED",
    "timing_validation": "VALIDATED",
    "uncertainty_profile_version": "string"
  },
  "cells": [
    {
      "cell_id": "string",
      "board_x_mm": 0.0,
      "board_y_mm": 0.0,
      "active_area_mm2": null,
      "status": "ACTIVE"
    }
  ],
  "frames": [
    {
      "timestamp_s": 0.0,
      "normal_force_n": [0.0],
      "quality": "VALID",
      "quality_flags": []
    }
  ]
}
```

`normal_force_n` 的长度和顺序必须与 `cells[]` 完全一致，值必须为有限且非负的 N 数值。缺帧不得补成零载荷；丢帧、长间隔、饱和、坏点、时间异常和测量不确定性必须通过 `quality` 与结构化 `quality_flags` 传递。

`measurement_profile` 只声明算法所需的物理有效性和可复现版本，不暴露设备专用标定方法。适配器、几何、测量一致性或不确定性版本变化必须使分析运行产生新的身份，不能覆盖历史结果。

## 4. 阶段元数据与责任

阶段边界、动作完成状态、前脚和安全事件可随同算法输入组装为 `stages[]`，并与 `frames[]` 使用同一时间域。它们由测试工作流产生；硬件适配器不得推断、改写或替代客户端动作状态机。

| 信息 | 硬件标准化层 | 算法层 |
|---|---:|---:|
| 协议解析、原始计数、零偏和载荷标定 | 负责 | 不读取 |
| 板面坐标、N、面积、实际时间和质量 | 负责 | 消费 |
| COP 与其他二级特征 | 不负责 | 内部计算 |
| 风险、评分和报告 | 不负责 | 内部计算 |
| 阶段/安全事件 | 透传，不推断 | 消费与解释 |

## 5. 接收与能力门控

算法接收方必须拒绝或隔离以下输入：未知 schema 或单位、坐标系不支持、重复 `cell_id`、非有限坐标、`normal_force_n` 长度不匹配或负值、非递增时间、未验证却标为 `VALIDATED` 的物理量，以及把二级特征塞入本契约的输入。

只有力、几何和时间满足所需测量有效性，并且对应帧质量允许时，算法才可发布正式指标。任何不能满足条件的硬件输入应产生明确的能力状态，而不是 0 分或静默的正式结果。

## 6. 一致性验证

每个新硬件适配器必须独立证明：已知载荷下的逐点/总力、已知物理位置下的坐标、实际时间序列、坏点/饱和/丢帧质量标志，以及跨适配器输入同一标准物理 fixture 时的等价物理输出。DO-P4864 只是首个适配器；其串口帧、列优先映射与原始 `uint8` 不属于本契约。
