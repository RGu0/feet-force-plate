# 开发用虚拟 CH340 / DO-P4864 设计

## 目标

在没有实体压力板时，为本机开发联调提供一个明确标记为模拟的 CH340 候选设备和一条真实可打开的伪串口数据流。采集端通过既有发现、打开和协议解析链路接收 DO-P4864 的 3,079-byte 帧。

## 范围与边界

- 仅在显式开发环境开关启用时，设备发现额外返回一个模拟候选；默认与生产行为不变。
- 候选在**应用层**具有通用 CH340 元数据：VID `0x1A86`、PID `0x7523`、描述 `USB-Enhanced-SERIAL CH340 (simulated)`，不申明为真实 USB 设备或稳定硬件身份。
- 启动器用 `socat` 创建固定成对 PTY：主机侧 `/tmp/ffp-dop4864-host`，设备侧 `/tmp/ffp-dop4864-device`。它们在运行期间存在，退出后移除。
- 发生器向设备侧以 20.7 Hz 写入：`FF AA 0C 07 01`、3,072 个 `0x00`、`0x00` CheckSum 候选、`FA`。每帧共 3,079 bytes，符合 observed compact 8-bit profile；全零输入只能用于数据流和工程行为调试，不代表压力、标定、受试者或临床证据。
- 串口打开参数沿用设备规格的 1,000,000 baud / 8N1。PTY 不具备真实 baud 电气时序，节律由发生器控制。
- 不增加 USB kext、驱动、真实 `/dev/cu.*` 节点、VID/PID 总线枚举或伪造 USB serial number；生产 CH340 自动发现规则不放宽。

## 结构

`client/device/development_simulator.py` 负责纯 Python 的帧契约、端点常量、开关读取和模拟 `SerialPortCandidate` 创建；它不启动子进程。

`scripts/run_dop4864_virtual_ch340.py` 是开发工具：启动 `socat`、等候两端点就绪、连续写帧、将 SIGINT/SIGTERM 转换为清理。它只依赖 Python 标准库与已安装的 `socat`。

`client/device/serial_transport.py` 的枚举函数在 `FEETFORCEPLATE_DEVELOPMENT_VIRTUAL_CH340=1` 时附加模拟候选，并沿用同一可用性探测。未启用时不变。

## 数据流与失败语义

```text
virtual generator -> /tmp/ffp-dop4864-device == socat PTY pair == /tmp/ffp-dop4864-host
    -> SerialByteTransport -> DaoOneP4864Parser -> existing acquisition pipeline
```

如果 `socat` 不可执行、端点没有在限定时间内出现或任一 PTY 写入失败，启动器以非零状态退出并报告开发工具错误；不会降级成空设备。模拟候选端点不存在/占用时由原有 availability probe 标为不可用。

## 验证

单元测试证明帧长度、固定字段、全零 payload、模拟候选的 CH340 元数据以及“默认不注入、显式开关才注入”。集成验证启动工具，使用 `SerialByteTransport` 和 `DaoOneP4864Parser` 读取并解码至少一帧，确认形状 `48x64`、dtype `uint8` 和全零矩阵。所有结果表述为开发模拟证据。
