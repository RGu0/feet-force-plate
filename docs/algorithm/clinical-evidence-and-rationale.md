# 临床证据与设计依据

| 项目 | 内容 |
|---|---|
| 对应协议 | `static-balance-fall-screen/1.0` |
| 资料核对日期 | 2026-07-21 |
| 用途 | 记录 V1 设计依据、适用边界和待验证假设 |

## 1. 使用原则

本文件记录 V1 静态平衡筛查算法采用的指南、队列研究、系统综述和药物共识，以及它们如何影响产品设计。

证据只用于：

- 确定风险方向；
- 选择值得采集的动作和指标；
- 识别可以直接作为高风险锚点的临床事实；
- 设定安全、报告和进一步评估边界。

证据不能直接用于：

- 把其他设备的绝对 COP 阈值复制到 DO-P4864；
- 把论文 OR、SMD 或相关系数直接变成产品权重；
- 把不同站距、时长、采样率和人群的临界值混用；
- 在未经本机标定和前瞻性验证时输出跌倒概率或医疗诊断。

## 2. 临床风险分层

### 2.1 World Falls Guidelines

- 文章：Montero-Odasso M, et al. *World guidelines for falls prevention and management for older adults: a global initiative.* Age and Ageing. 2022.
- 原文：[PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9523684/)
- 算法：[World Falls Guidelines Algorithm](https://worldfallsguidelines.com/algorithm)

关键结论：

- 老年跌倒风险应进行多因素评估；
- 过去 12 个月反复跌倒（`>=2`）、跌倒造成需要医疗处理的伤害、跌倒后长时间无法自行起身、疑似短暂意识丧失/晕厥和衰弱属于高风险特征；
- 中间风险人群需要针对性的平衡/力量训练或专业转介；
- 高风险人群需要更完整的多领域评估和密切随访。

对本设计的影响：

- 使用过去 12 个月作为统一跌倒史窗口，不自造“最近 3 个月”的临床定义；
- 明确高风险背景优先于压力板分数；
- 单次未受伤跌倒进入一般背景风险，不自动等同反复或严重跌倒；
- 晕厥和意识丧失进入高风险及进一步专业评估提示。

### 2.2 CDC STEADI

- 工具：*Algorithm for Fall Risk Screening, Assessment, and Intervention.*
- 链接：[CDC STEADI Algorithm](https://www.cdc.gov/steadi/media/pdfs/STEADI-Algorithm-508.pdf)
- 自评工具：[Stay Independent](https://www.cdc.gov/steadi/pdf/steadi-brochure-stayindependent-508.pdf)

关键结论：

- 三个核心问题是过去一年是否跌倒、站立/行走是否不稳、是否担心跌倒；
- 任一问题阳性都提示需要进一步评估；
- 跌倒阳性后继续询问次数和是否受伤；
- 评估领域包括步态、力量、平衡、药物、直立性低血压、视力、足部和共病。

对本设计的影响：

- 将三项核心问题放入测试前必选信息；
- 保留跌倒次数和受伤/就医后果；
- 压力板只是多因素筛查中的一个客观组成部分；
- 报告给出进一步评估建议，不把筛查当成诊断。

## 3. 静态摆动与未来跌倒

### 3.1 诊断性平衡测试系统综述

- 文章：Kozinc Ž, et al. *Diagnostic Balance Tests for Assessing Risk of Falls and Distinguishing Older Adult Fallers and Non-Fallers: A Systematic Review with Meta-Analysis.* Diagnostics. 2020.
- 链接：[PubMed](https://pubmed.ncbi.nlm.nih.gov/32899201/) / [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC7554797/)

关键结论：

- 纳入 19 项前瞻性研究和 48 项回顾性/病例对照研究；
- 在压力中心指标中，摆动面积与跌倒的关联最一致；
- 摆幅和轨迹也具有潜力；
- 没有发现消除视觉一定能为总体跌倒风险判断带来额外收益；
- 研究协议和阈值高度异质。

对本设计的影响：

- V1 采集轨迹面积、路径、速度、AP/ML RMS 和范围；
- 闭眼变化作为补充领域，不预设固定高权重；
- 不复制系统综述中的设备特定临界值。

### 3.2 1,877 人前瞻性队列

- 文章：Johansson J, et al. *Increased postural sway during quiet stance as a risk factor for prospective falls in community-dwelling elderly individuals.* Age and Ageing. 2017.
- 链接：[PubMed](https://pubmed.ncbi.nlm.nih.gov/28531243/)

关键结论：

- 1,877 名 70 岁社区人群，随访 6 和 12 个月；
- 睁眼和闭眼条件下的 COP 摆动长度均能独立预测未来跌倒；
- 论文阈值来自特定设备、时长和人群。

对本设计的影响：

- 同时保留睁眼基础摆动和闭眼相对变化；
- 文献绝对毫米阈值不迁移到当前未标定 `uint8` 压力板。

### 3.3 测力台前瞻性研究综述

- 文章：Piirtola M, Era P. *Force platform measurements as predictors of falls among older people—a review.* Gerontology. 2006.
- 链接：[PubMed](https://pubmed.ncbi.nlm.nih.gov/16439819/)

关键结论：

- 不同研究结果并不完全一致；
- ML 方向的平均速度、幅度和 RMS 是多项研究中与未来跌倒显著相关的指标。

对本设计的影响：

- 半串联和双足阶段均重点保留 ML RMS、ML 范围和速度；
- 不把单一指标作为疾病诊断或唯一风险结论。

## 4. 半串联和动作完成

### 4.1 2025 年前瞻性研究

- 文章：Brown C, et al. *Narrow Walk, Condition II, Semi-Tandem, Tandem, and Single Leg Stance Test Failure Could Predict Falls in Older Adults.* 2025.
- 链接：[PubMed](https://pubmed.ncbi.nlm.nih.gov/40386943/) / [期刊页面](https://journals.sagepub.com/doi/10.1177/00469580251337269)

关键结论：

- 952 名 60–97 岁成年人；
- 半串联失败与未来跌倒相关，调整后 OR 约 2.59；
- 闭眼感觉整合条件失败也与未来跌倒相关；
- OR 是研究关联强度，不是产品评分权重。

对本设计的影响：

- 动作能否完成本身作为结果；
- 平衡性失败不因轨迹不足 20 秒而删除；
- 半串联进入 V1，但 OR 不直接变成 40% 或其他固定权重。

### 4.2 四种站姿 6 个月纵向研究

- 文章：*Standing balance test for fall prediction in older adults: a 6-month longitudinal study.* BMC Geriatrics. 2024.
- 链接：[PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11566129/) / [BMC](https://link.springer.com/article/10.1186/s12877-024-05380-9)

关键结论：

- 双足、半串联、串联和单脚的支撑面逐渐缩小，摆动增加；
- 跌倒者在半串联中可表现出更大的 AP/ML 摆动；
- 该研究中真正与 6 个月跌倒显著相关的主要是串联/单脚完成时间和 ML 幅度；
- 作者建议至少约 23 秒可能更容易暴露轻微缺陷。

对本设计的影响：

- 20 秒半串联是安全、设备面积和总流程时长之间的产品折中；
- 20 秒略短于该研究建议，必须通过本地重复性和随访验证；
- 不因一篇研究将半串联设定为固定最高权重。

### 4.3 左右脚位置研究

- 文章：Wang T, et al. *Characteristics of static balance performance in 4-stage balance test in the healthy older adults.* International Journal of Neuroscience. 2025.
- 链接：[PubMed](https://pubmed.ncbi.nlm.nih.gov/38305048/)

关键结论：

- 115 名健康社区老年人；
- 在该样本中，改变半串联、串联和单脚任务的左右脚位置没有显著影响整体稳定性；
- 结果不等于个体的显著左右差异没有意义，也不能直接推广到神经、关节或疼痛人群。

对本设计的影响：

- 左右脚在前均采集，前脚和方向必须记录；
- 主要左右差异可以进入 V1 评分，但必须超过设备重复误差和参考人群阈值；
- 轻微差异不扣分，也不诊断单侧疾病。

## 5. 站距、时长和采样率

### 5.1 站距影响

- 文章：*Influence of stance width on standing balance in healthy older adults.*
- 链接：[PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9618500/)

关键结论：

- 站距会显著影响静态摆动，尤其是 ML 参数；
- 自选站距与部分标准站距可能相近，但姿势必须保持一致或记录。

对本设计的影响：

- 双脚并拢和半串联脚位需要明确引导；
- 保存足底接触掩码、角度、站距和相对位置；
- 参考人群必须使用同一协议。

### 5.2 试验时长

- 文章：Richmond SB, Otto G, Dames KD. *Characterization of trial duration in traditional and emerging postural control measures.* Journal of Biomechanics. 2023.
- 链接：[PubMed](https://pubmed.ncbi.nlm.nih.gov/36641826/)

关键结论：

- 不同指标达到稳定估计所需时长不同；
- 部分速度指标需要 60–120 秒，时间到边界和非线性指标可能需要更长；
- 20 秒更适合基础时域/空间指标，不适合复杂频域和非线性结论。

对本设计的影响：

- V1 只计算路径、速度、RMS、稳健范围和椭圆面积等基础指标；
- 排除熵、DFA、复杂频谱和长时依赖指标。

### 5.3 低成本设备重复性

- 文章：*Closing the gap while standing still: clinimetric properties of a low-cost balance platform and a user-friendly app for posturography.* PeerJ. 2025.
- 链接：[PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11804768/)

关键结论：

- 约 20 Hz、20 秒的设备可以与参考系统获得较高并行效度；
- 安静站立的重测信度仍可能只有较差到中等水平。

对本设计的影响：

- 当前约 20.7 Hz 可以支持 V1 候选指标，但必须做本机重复性验证；
- 左右差异只有超过最小可检测变化后才能进入评分。

## 6. 跌倒相关药物

### 6.1 STOPPFall 共识

- 文章：Seppala LJ, et al. *STOPPFall: a Delphi study by the EuGMS Task and Finish Group on Fall-Risk-Increasing Drugs.* Age and Ageing. 2021.
- 链接：[PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC8244563/)

关键结论：

- 共识纳入苯二氮䓬及类似药物、抗抑郁药、抗精神病药、抗癫痫药、阿片类、抗胆碱能药、利尿剂、部分 α 受体阻滞剂、抗组胺药等；
- 不同亚类、剂量、药物组合和适应证会影响真实风险；
- 药物审查应由医生或药师完成。

对本设计的影响：

- 只采集少量通俗类别标签，不采集具体药名、剂量和处方；
- 标签作为背景风险，不单独直接判高风险；
- 报告只建议咨询医生或药师，不建议自行停药。

### 6.2 系统综述和 Meta 分析

- 精神类药物：[PubMed 29402652](https://pubmed.ncbi.nlm.nih.gov/29402652/)
- 其他药物：[PubMed 29402646](https://pubmed.ncbi.nlm.nih.gov/29402646/)

关键结论：

- 抗精神病药、抗抑郁药和苯二氮䓬类与跌倒的关联较一致；
- 阿片类、抗癫痫药和多重用药在 Meta 分析中也与跌倒增加相关；
- 观察性研究存在适应证混杂和异质性。

对本设计的影响：

- 核心标签聚焦镇静/助眠/抗焦虑、情绪/精神、强效止痛和抗癫痫；
- 血压/利尿和容易困倦的其他类别仅在伴相关症状时进入规则。

## 7. 睡眠问题

- 文章：Knechel NA, Chang P-S. *The relationships between sleep disturbance and falls: A systematic review.* Journal of Sleep Research. 2022.
- 链接：[PubMed](https://pubmed.ncbi.nlm.nih.gov/35288982/)

关键结论：

- 睡眠碎片、极短或极长睡眠及部分失眠研究与跌倒有关；
- 截点、研究设计和测量方法异质，难以形成统一临界值。

对本设计的影响：

- 失眠本身不进入 V1 独立计分；
- 助眠/镇静药物进入可选药物标签；
- 测试当下明显困倦或反应迟缓作为安全观察信息。

## 8. 证据等级与设计映射

| 设计项目 | 当前证据强度 | V1 用法 |
|---|---|---|
| 过去 12 个月反复/严重跌倒 | 指南明确 | 直接高风险背景 |
| 晕厥、意识丧失 | 指南明确 | 高风险背景和进一步评估 |
| 不稳、担心跌倒 | 临床工具明确 | 一般背景风险 |
| 多项动作无法完成/扶持 | 临床和前瞻性研究支持 | 高风险完成规则 |
| 半串联单项失败 | 前瞻性关联 | 至少中风险，伴明显失稳则高风险 |
| 摆动面积、轨迹、速度 | 系统综述/队列支持 | 核心压力指标 |
| ML RMS/范围/速度 | 多项前瞻性研究支持 | 重点指标 |
| 闭眼相对变化 | 有关联但增益不一致 | 补充领域，不设固定权重 |
| 左右脚在前差异 | 个体意义可能存在，群体证据有限 | 超过重复误差和参考阈值后计分 |
| 药物类别 | 指南、共识和 Meta 分析 | 可选背景标签，不单独判高 |
| 失眠 | 关联异质 | 不独立计分 |
| 20 秒复杂频域/非线性指标 | 证据不足 | V1 排除 |

## 9. 不能从文献直接得到的内容

以下内容必须由本项目自行验证：

1. DO-P4864 原始 `uint8` 值的量纲和标定；
2. 20.7 Hz、20 秒条件下各指标的重测信度；
3. 固定左转 90°后的 AP/ML 坐标变换；
4. 当前板面上的标准半串联足位；
5. 本设备的参考人群分布和左右差异最小可检测变化；
6. 综合筛查评分与未来 12 个月跌倒之间的真实校准关系；
7. 不同年龄、性别、机构类型、疾病背景和助行器人群中的公平性；
8. 低/中/高分界在目标运营场景中的敏感度和特异度。

在这些验证完成前，V1 只能称为“基于临床相关性的初步筛查规则”，不能称为医疗级跌倒风险预测模型。

## 10. 后续验证路线

1. 完成设备坐标、标定、重复性和 20 秒指标验证；
2. 建立 60 岁以上、统一协议的冻结参考样本；
3. 以当前规则做影子运行，检查分布、重测和异常案例；
4. 记录 6 和 12 个月跌倒次数、受伤和就医结局；
5. 用训练/验证分离、交叉验证和外部验证评估模型；
6. 报告 AUC 之外的敏感度、特异度、阳性预测值、阴性预测值和校准；
7. 检查年龄、性别、机构和功能状态亚组偏差；
8. 经批准后发布新算法版本，对历史原始数据重算，不覆盖旧结果。
