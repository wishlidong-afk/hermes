# 近期故障补丁统一外审：接收与处置记录

日期：2026-10-30（Asia/Shanghai）。

**组合正确性外审 PASS；精确范围获提交/推送技术许可。本文不执行或授权 Git 写操作，不构成部署批准。DEPLOY HOLD；A2 OPEN；Phase B 未启动。**

## 1. 来源与本轮范围

原始附件：`/Users/liweishi/.codex/attachments/f04df43f-914d-4478-9922-1f499543ac5d/已粘贴的文本.txt`。

原文归档：`docs/history/2026-10-30_daily_remediation_combined_external_audit_report.md`。附件与归档逐字节相同，均为 SHA256 `680b9dd9373b428db2a30a18c400656554a99af55304b96dd29056ce0d61e95b`；保留原文末尾及用量文字，不代外审员修订正文。

本轮仅新增原文归档、本文，并向统一外审入口追加接收注记。生产实现、测试、依赖、旧三份交接及所有冻结证据保持原字节。原入口追加前 SHA 为 `7047f4e078750e36b4188dd585f82ce564bbe0b23f325984b437c6f640d923c2`，旧前缀保留。

候选仍为独立 clone `hermes-daily-failure-remediation-2026-10-23`，HEAD `2db0cdc562309b6222a69aaee8dbdaf51c763b93`；不是主目录的累积 A2 候选。外审技术许可不等于用户本轮要求自动提交或部署，origin 仍为本机主仓路径。

## 2. 两处外审叙述更正

### SOXL 价格差与成交量差不能混用

外审自然报告表中的 `SOXL PRICE_MISMATCH(3.1067%)` 数值归属错误。重新只读原始 `market_admission_2026-10-22.json`，三条 SOXL 2026-10-21 拒收均为：

- `status=PRICE_MISMATCH`。
- `max_ohlc_diff_pct=1.1024`，对应此前核对的最高价 104.96 / 106.13，超过 1% 价格上限。
- `volume_diff_pct=3.1067`，不是触发拒收的价格差。

本记录纠正引用口径，保留外审原文，不改证据或阈值；不影响本片实现的 PASS 判定，也不证明哪个源的历史行情正确。

### 转发等待分支已有自然执行观察

外审末尾沿用“forwarder 新等待规则的自然执行仍未观察”，与统一入口第 6 节的更新不符。10-28 本对话已观察到：当天报告初缺、只读检查实际主任务、等待约 30 秒、报告到达后核对并转述，未补跑生成。

这只关闭“等待分支从未自然执行”这一观察项。不是调度偏移根因证明，不代表十分钟超时、主任务异常、损坏或冲突报告等全部分支已有自然样本，也不是候选代码部署证明。无需为此重复生成报告或修改任务。

## 3. P2/P3 逐项处置

| 外审项 | 处置 | 保留的边界 |
|---|---|---|
| P2-1 部署环境代理 TLS | 接受，列为部署前显式检查项；本轮未检查或改动生产环境 | 先核实实际 HTTP 客户端的代理/CA 配置与新 urllib3 行为是否适用；源码无自定义代理不替代环境核查。不得输出代理凭证或关闭 TLS 校验 |
| P2-2 detail 240 字符截断 | 接受为展示残余限制，本轮不改代码 | 原代码已有 240 上限；前插 summary 会减少旧详情可见长度，完整原始准入记录仍是证据。未承诺超长文案无截断。若后续调整，新增长文案回归并重新绑定该增量，不沿用旧字节批准 |
| P3-1 次级 health 仅捕获 Exception | 保持现状 | 正常 I/O 异常保留原失败；KeyboardInterrupt/SystemExit 可传播，不承诺次级 BaseException 下仍保留原异常。不为冻结本片新增吞中断逻辑 |
| P3-2 四个 advisory 与五行展示 | 接受计数口径说明 | 按不同 advisory ID 计数为 4；外审自述当前旧锁输出 5 行是同一 certifi ID 的两个修复版本。不是本轮作者重新扫描，旧扫描 JSON 不修改 |
| P3-3 next_scheduled_at | 接受文档澄清，不改字段或页面 | 源码以 attested_at 调用 _next_natural_daily_at；表示认证后的首个自然调度点，不是相对今天的下一次执行时间。旧值不单独否定 CERTIFIED |
| P3-4 daily 证据仅一份 equivalence | 接受非自含性，沿组合材料复核 | daily 片原 1490/152.02s 无长期保存全套日志；dependency 包的 1490/158.89s 是后续不同环境的独立组合执行，不能充当原运行日志。当前组合使用 conflict 包 1513/152.21s 及外审自述 1513/201.14s，不伪造旧日志 |
| P3-5 342/343 绑定时点 | 接受并保留 | 发布候选引用当前 343 文件 / 4e2ed959... 的 strict；旧 342 / 67fa82a4... 是旧增量，不能覆盖新增测试字节；旧材料不重生成 |

代理适用性检查针对这次 Python 依赖升级；没有把未变 OS/JVM 全部信任库改造、outbox 或报告多文件断电原子化自动扩大成本补丁的必做特性。不宣称这些未覆盖能力已存在；若要扩大保证，应单独定义需求和验证。

## 4. 本轮直接核验与外审执行归属

外审自述的 98 focused、1513 full / 201.14s、8/8 governance、mypy/Ruff/compile/pip check、安全扫描、独立四日期和源码指纹均属于外审员执行。本轮没有重复执行未变化代码的全套，也不将其日志归为作者本轮产物。

本轮作者直接读取了外审员留下的两个 strict JSON 与两个离线行为 JSON：

| 临时文件，根为 /tmp/hermes-remediation-audit | SHA256 |
|---|---|
| `equivalence-candidate.json` | `f88f9e2e00cec65b4edc442d78fa749bf857e58f24dddf3a5ab223edf60fde66` |
| `equivalence-old-runtime.json` | `7f34a9365e39c0282ba818fa450b4902621375c9400d81d1ad959843437a8939` |
| `probe-old.json` | `0e7823bac13b26da659617a946e91e309da23fc2e7344120f6aca8675ab002fc` |
| `probe-new.json` | `c1ebc71ae147d338b494140a819dc733ac3174a7cf6ea8973dbaa96a1c64cf84` |

两个 strict 均 4/4 equal、strict_differences 空，候选 343 文件、manifest `4e2ed9596e6c61940b161ec28c2547ce0b7e4672499f4634cd88cdd2d294cfa8`；新旧 runtime 的四日期完整 payload/artifacts 摘要另按结构核对。行为报告分别 FAIL/PASS，network_attempts=0、TLS 验证开启。临时文件不复制入 Git、不保证永久保留；读取结果不是作者重新运行探针或逐条独立复验所有外审命令。

原 26 件证据绑定及六个当前实现/测试摘要重新核对；旧源码、证据及主目录受保护绑定的前后核对结果见本轮最终工具输出。未执行新的金融网络请求、实时缓存检查或漏洞库扫描。

## 5. 提交说明与后续顺序

建议未来提交按三片分列，不将它们写成依赖-only 或整个 A2 发布：

```text
fix: preserve daily failure evidence and clarify market conflicts

- Daily: correct final receipt step and bind failed health to this invocation.
- Security: update only urllib3/certifi; retain the other 30 lock records.
- Health: display unique rejection identities and comparison attempts only.
- Include the two regression files and declared evidence/handoff documents.
- Combined independent review PASS; current strict binds 343 source files.
- Preserve 342-file historical evidence and the original red audit results.
- Review SOXL percentage and forwarding-observation corrections in followup.
- Proxy TLS applicability remains a deployment preflight item.

DEPLOY HOLD; A2 OPEN; Phase B not started.
```

实际 Git 写操作仍需用户要求执行；显式路径清单沿统一入口，新增本次 report/followup 文档，不得 `git add -A`、混入主目录 A2、三份九月计划或私有 capture。提交技术许可不证明 GitHub 已同步；本地 origin 不是 GitHub，需另行确认发布目标。

下一项可执行发布准备：在授权边界内做只读部署预检（代理/CA 适用性、实际目标、活跃 writer 与 config 保留方案），之后按用户授权提交/推送并获得实际组合 CI；真正 R6 另需明确部署批准。不得为消红运行 official daily。部署后自然观察不能由旧 live 的五日结果代替。A2 最新通路及剩余工程另按其交接推进，不借本外审关闭。

本次接收没有新的实现修复要求，不需要仅为文档接收再开一轮相同代码外审。**组合正确性 PASS；Git 技术许可限精确候选；部署 HOLD，A2 OPEN。**
