# 硬件层到算法层的标准压力信息流 V1

| 项目 | 内容 |
|---|---|
| 接口版本 | `physical-pressure-session/1.0` |
| 生产方 | RAY-117 硬件标准化层 |
| 消费方 | 本地/云端算法层、能力门控、规则和报告 |
| 加解密 | 不在本文定义，由通信层和存储层负责 |
| 状态 | 设计基线；等待 RAY-117 真机载荷、几何、时间和质量证据 |

## 1. 统一边界

硬件层只输出标准压力信息流：

```text
设备原始协议 / 原始计数
  → physical-pressure-session/1.0
      每点板面坐标（mm）
      每点法向载荷（N）
      每帧实际时间
      几何/面积、质量、标定和版本
  → 算法层
      姿态归一化、COP、速度、RMS、范围、椭圆、阶段差异
      风险规则、综合评分和报告
```

硬件层不计算或传输 COP、位移、速度、RMS、步态、跌倒风险、报告字段或客户端特征。所有压力分析和特征提取由算法层完成。

如果硬件只有原始计数、零点修正计数或相对载荷，没有经批准的法向载荷 N 语义，则输出必须为 `DEGRADED/UNSUPPORTED`，不得把相对计数改名为 N 或 Pa 进入正式分析。

## 2. 文件格式

规范交换格式为 UTF-8 JSON；通信层可使用二进制/列式格式，但必须保持同一字段语义。建议文件名：

```text
<session_id>.physical-pressure-session.v1.json
```

加解密、签名、密钥、重试和对象存储不属于本文件。文件由 session manifest/event 以外部字段引用：

```json
{
  "input_schema_version": "physical-pressure-session/1.0",
  "hardware_adapter_version": "adapter/do-p4864/1.0",
  "geometry_profile_version": "geometry/do-p4864/1.0",
  "measurement_conformance_version": "measurement/1.0",
  "calibration_profile_version": "calibration/do-p4864/1.0",
  "uncertainty_profile_version": "uncertainty/do-p4864/1.0",
  "session_id": "019c0000-0000-7000-8000-000000000001",
  "sha256": "<64 lowercase hex characters>",
  "frame_count": 100,
  "cell_count": 3072
}
```

这些版本必须进入 `AnalysisRun` 身份；任一版本或摘要变化都产生新的分析运行，不能覆盖历史结果。

## 3. 标准压力信息流字段

### 3.1 顶层字段

```json
{
  "schema_version": "physical-pressure-session/1.0",
  "session_id": "uuid",
  "coordinate_frame": "BOARD_X_RIGHT_Y_DOWN",
  "coordinate_unit": "mm",
  "force_unit": "N",
  "area_unit": "mm2",
  "time_unit": "s",
  "measurement_profile": {},
  "cells": [],
  "stages": [],
  "frames": []
}
```

生产环境必须拒绝未知顶层字段。`schema_version`、`session_id`、单位、`measurement_profile`、`cells`、`stages` 和 `frames` 均为必填。

### 3.2 `measurement_profile`

```json
{
  "profile_version": "measurement-profile/1.0",
  "measurement_conformance_version": "measurement/1.0",
  "calibration_profile_version": "calibration/do-p4864/1.0",
  "uncertainty_profile_version": "uncertainty/do-p4864/1.0",
  "physical_validation": "VALIDATED",
  "timing_validation": "VALIDATED",
  "coordinate_validation": "VALIDATED",
  "force_validation": "VALIDATED",
  "geometry_validation": "VALIDATED"
}
```

正式算法输入要求物理、时间、坐标、载荷和几何状态均为 `VALIDATED`。未达到时保留质量结果，但不发布正式压力指标。

### 3.3 `cells[]`：板面坐标与感应点声明

每个感应点必须提供：

| 字段 | 类型 | 规则 |
|---|---|---|
| `cell_id` | string | 会话内唯一，顺序稳定 |
| `x_mm` | number | 感应点有效区域中心的板面 X 坐标 |
| `y_mm` | number | 感应点有效区域中心的板面 Y 坐标 |
| `active_area_mm2` | number/null | 经验证有效面积；未知时为 `null`，不得伪造 |
| `status` | enum | `ACTIVE` / `EXCLUDED` |

点宽、点高、点间距和阵列数量属于硬件几何/适配器版本信息；算法不根据阵列行列或内存顺序自行重建坐标，只使用 `cells[]` 中的实际坐标。

### 3.4 `frames[]`：载荷、时间与质量

```json
{
  "timestamp_s": 0.0,
  "normal_force_n": [100.0, 0.0],
  "quality": "VALID"
}
```

规则：

- `normal_force_n` 的数量必须等于 `cells[]` 长度；
- 法向载荷必须是有限、非负的 N 数值；
- `timestamp_s` 使用实际单调时间，必须严格递增，不按额定采样率补帧；
- `quality` 至少支持 `VALID` / `INVALID`；缺帧、饱和、坏点、长间隔和时间异常必须在外部质量/manifest 中保留枚举；
- 算法不得把 `quality=INVALID` 的帧当作有效压力数据，也不得把缺失帧当成零载荷。

## 4. 四阶段动作元数据

动作状态由客户端测试工作流产生并透传，硬件层不得推断或改写。`stages[]` 必须按以下顺序、连续窗口提供四个阶段：

1. `BILATERAL_EYES_OPEN`：双足并拢、睁眼、朝前；
2. `BILATERAL_EYES_CLOSED`：双足并拢、闭眼、朝前；
3. `SEMI_TANDEM_LEFT_FORWARD`：固定左转 90°、左脚在前、睁眼；
4. `SEMI_TANDEM_RIGHT_FORWARD`：固定左转 90°、右脚在前、睁眼。

每个阶段至少包含：

```json
{
  "stage_id": "BILATERAL_EYES_OPEN",
  "start_s": 0.0,
  "end_s": 20.0,
  "completion_status": "COMPLETED",
  "actual_completion_s": 20.0,
  "subject_orientation": "FORWARD",
  "forward_foot": "NONE",
  "step_count": 0,
  "moved_feet": false,
  "touched_rail": false,
  "staff_supported": false,
  "near_fall": false,
  "eyes_opened_early": false,
  "stop_reason": "NONE"
}
```

`TECHNICAL_INVALID`、`PROTOCOL_INVALID` 和 `NON_BALANCE_STOP` 只表示数据/流程状态，不自动等同于受试者平衡风险；`BALANCE_FAILURE`、`SAFETY_ABORT`、工作人员扶持和近乎跌倒由算法规则层单独处理。

## 5. 算法层责任

算法层从板面坐标、法向载荷、实际时间和阶段姿态元数据计算：

```text
板面坐标 + 阶段姿态
  → 受试者 ML/AP 归一化
  → COP
  → 路径、速度、RMS、P5-P95 范围、95% 椭圆、力/接触面积变化
  → 睁闭眼、半串联、左右前脚差异
  → 能力门控、参考分级、风险规则和报告
```

算法层不读取设备型号、原始计数、阵列内存顺序或设备专用标定分支；适配器、几何、载荷、测量一致性或不确定度版本变化会触发新的 `AnalysisRun`。

## 6. 拒绝和降级规则

接收方必须拒绝或隔离：

- schema、字段、单位、坐标系或版本不支持；
- `cells[]` 重复 ID、非有限坐标、负载荷、长度不匹配或非递增时间；
- 缺失四阶段、阶段顺序错误、窗口不连续或方向/前脚语义错误；
- 未验证载荷、面积、坐标或时间却标为 `VALIDATED`；
- 把 COP、速度、风险或报告字段塞入硬件层文件；
- 把原始/相对计数伪装成 N/Pa。

技术输入失败只进入内部安全错误码和质量状态，不生成 0 分；动作完成失败则作为独立风险证据交给 RAY-118。

## 7. 责任矩阵

| 信息/能力 | 硬件层 | 算法层 | 通信层 |
|---|---:|---:|---:|
| 设备解析、原始计数和板面几何 | 负责 | 不读取 | 传输 |
| 板面坐标、法向载荷 N、实际时间 | 负责并声明版本 | 消费 | 传输 |
| 姿态归一化、COP、速度和全部压力特征 | 不负责 | 负责 | 不负责 |
| 阶段完成、左右前脚和安全事件 | 工作流透传 | 解释规则 | 传输 |
| 加解密、签名、重试、对象存储 | 不负责 | 不负责 | 负责 |

## 8. 验收边界

本接口定义字段和职责，不代表 DO-P4864 已完成法向载荷、有效面积、坐标方向、时间不确定性或跨设备验证。RAY-117 在这些证据完成前保持 `In Progress/In Review`，云端算法不得发布正式压力指标或完整报告。
