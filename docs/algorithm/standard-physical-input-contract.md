# 标准物理压力输入契约

本文件保留为算法文档的稳定入口；V1 的字段、文件格式、拒绝规则和责任矩阵以[硬件层到算法层的标准压力信息流 V1](physical-input-interface-v1.md)为规范正文。

硬件内部的原始计数、零校正值、候选力和校准证据使用独立的
[`physical-sensor-observation/1.0`](schemas/physical-sensor-observation-1.0.schema.json)，绝不作为算法输入。算法只消费经过验证的
[`estimated-force-session/1.0`](schemas/physical-pressure-session-1.0.schema.json)。
