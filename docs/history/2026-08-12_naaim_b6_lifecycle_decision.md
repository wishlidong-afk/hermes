# NAAIM / MSTR B6 输入生命周期裁决

日期：2026-08-12
状态：生效，报告层约束
范围：WebUI、system health、运维文档；不修改评分、路由、因子注册表或配置

## 决策

Hermes 必须把以下三类状态分别表达，不能继续统称为“代理”“缺项”或“未接线”：

| 类型 | 当前对象 | 报告措辞 | 策略语义 |
|---|---|---|---|
| 已退役计分来源 | A2 NAAIM | `已退役来源，等待 SLO 缺失路径` | 最后一份认证历史保持不可变；在 SLO 内仍按 PIT 使用，超龄后进入既有 missing_weight 防御路径 |
| 计分输入缺失 | MSTR B6 valuation | `计分输入缺失 5 分` | `max_score=5`，不是占位；`use_b6_mnav_valuation=false` 时 MSTR B6 明确缺失并保留既有计分缺失语义 |
| 非计分占位 | A2 CNN、B5 social、D-M4、D-M5 | `非计分占位` | `max_score=0`，只用于可见性，不进入策略 missing_weight、盲区惩罚或得分上限 |

## NAAIM

`data_naaim` 保持 ON，不代表公共抓取仍可用。公共 workbook 自
2026-08-01 起为 `RETIRED_PAYWALL`，最后认证 canonical 与 ledger 冻结，周五仅探测官方访问是否恢复。系统不得使用镜像、新闻、AAII、PCR 或推算值回填。

保留 flag ON 的原因是维持现有 PIT 历史和保守缺失路径，而不是宣称自动化仍健康：

1. 认证行仍在 SLO 内时，A2 可以使用当时可见的数据。
2. 行超过 SLO 后，`use_soft_data_max_age` 将其置为缺失。
3. A2 NAAIM 的缺失权重按既有配置处理，不能因来源退役被静默归零。
4. `EVIDENCE_DRIFT`、canonical 缺失或 ledger 绑定失效仍然 fail closed。

未来替代 NAAIM 的 CFTC TFF 候选必须先完成独立 PIT 研究并进行一次预注册 formal gate；若接入，必须替换 A2 的既有位置，不得向已饱和的 A 模块叠加权重。

## MSTR B6

MSTR B6 是一个真实的 5 分计分槽位。mNAV 消费实验已经 gate-failed，因而
`use_b6_mnav_valuation` 与 `data_mstr_mnav` 保持 OFF；这不把 B6 变成零分占位。当前报告必须明确显示 MSTR B6 的 5 分输入缺失。

FNGU/SOXL 的 B6 仍使用各自已接线的估值百分位，本裁决不改变它们。任何未来 MSTR B6 恢复都需要新的自动 PIT 数据链、新先验和一次新的 formal gate，不得复跑或微调已拒绝的 mNAV 实验。

## 非计分占位

以下定义只有可见性用途：

- `A2_CNN_FEAR_GREED`
- `B5_SOCIAL_EUPHORIA`
- `D_M4_BALANCE_SHEET_PROXY`
- `D_M5_CRYPTO_SENTIMENT`

它们必须只出现在 WebUI 折叠的“非计分占位”区。现有
`use_scored_missing_weight=true` 路径已经证明这些 `max_score=0` 项不会进入策略 missing_weight；报告层不得再把它们与 MSTR B6 放在同一缺失告警中。

## 不变项

- 不翻转任何 feature flag。
- 不改 `config.json`、模块 cap、因子权重、状态阈值或路由。
- 不改 NAAIM/B6 的现有评分与 missing_weight 行为。
- 不借本裁决恢复任何已拒绝实验。
- 四日期评分、状态、路由、目标仓位和 `input_hash` 必须保持一致。

## 验证

- WebUI 测试：四个零分占位只出现在折叠区；NAAIM 与 MSTR B6 显示指定措辞。
- Health 测试：NAAIM、MSTR B6、非计分占位分别汇报。
- 既有 `test_scored_missing_weight.py`：零分占位不进入 operational missing weight。
- 四日期隔离回放：保护输出和 `input_hash` 不变。
