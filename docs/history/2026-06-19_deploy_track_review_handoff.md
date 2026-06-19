# Deploy-track fix + live rollout — review handoff for Agent A

> 日期：2026-06-19
> 用途：交给 Agent A 独立复审 Agent B 的「部署修复 + 首次 R1-R5 上线 + 权限归一化」工作
> repo / 分支：`~/Documents/github/hermes` · `hermes-docs`
> repo/origin HEAD：以 `git rev-parse --short HEAD` 为准（本文是 hermes-docs 上的文档提交，每次提交都会使 HEAD 前进，故此处不钉死哈希）　|　**live VERSION：`71e939c`**（已部署、已验收）
> 关键前提：R1-R5 包代码已在前一轮复审通过；本轮只动**部署机制**和一次**真实上线 + live 权限**。

**不要相信本文的自我评价。** 从源码追到真实行为，优先构造反例。我（Agent B）这轮**真的改了 live**（跑了部署、chmod 了 live CSV），所以你既要审代码，也要独立确认 live 没被弄坏。

---

## 1. 我做了什么（要被你审的）

| commit | 内容 |
|---|---|
| `71e939c` | 部署脚本三处修复（下方 §3）|
| `0722e78` | live 部署后 `.hermes` 的 allowlist commit（**不在本 repo**，在 `~/.hermes` git）|
| `e89111a` | live CSV 权限归一化记录（`building/reports/csv_perms_normalization_2026-06-19.md`）|

外加两次**真实部署**：第一次（→`522fa16`）在 step 7 失败并自动回滚到 `2beea7d`；修复后第二次（→`71e939c`）成功。以及删除冗余 worktree `codex/stability-b-deploy`。

### 背景：第一次部署为什么失败
首次真部署 verify_live PASS 后，step 7（`.hermes` allowlist `git add`）失败 —— `~/.hermes/.gitignore` 忽略 `bin/` 和 `tests/`，而 allowlist 含 `bin/run_daily.sh`/`bin/serve_dashboard.sh`（未跟踪+被忽略），`git add`（无 `-f`）拒绝 → 「commit 失败即 fatal」触发 → 锁内精确回滚 → 退码 3。**安全机制首秀成功**（零损害还原）。同一次还暴露了 verify_live 的 `MARK` unbound bug。

---

## 2. 必须仍然成立的不可变式

1. Hermes 只读、永不下单；live `config.ibkr.readonly` 仍为 `true`（部署对 config 答了 **N**，未改）。
2. `.hermes` 部署 commit 只含 allowlist（代码 + VERSION + 入口脚本），**绝不含运行态/敏感数据**（这是审计 S8 的修复，`-f` 不能把它打破）。
3. verify_live 只产隔离 `manual_rerun`，不写官方 receipt/state/live audit。
4. live 现在 == 已 review 的 R1-R5 包代码（部署没引入额外改动）。
5. CSV 权限归一化**只改 mode、不改内容**。

---

## 3. 逐项审核（每项：改了什么 → 怎么验 → 构造什么反例 → 应有什么测试）

### 3.1 [最高风险] `git add -f` 会不会重新引入 S8 的运行态/敏感数据？

**改动**：`scripts/deploy_to_live.sh` `stage_deploy_allowlist()` 的 `git add` → `git add -f`，强制越过 `.hermes/.gitignore`（忽略 `bin/`）加入口脚本。

**为什么危险**：`-f` 强制加被忽略文件。如果 allowlist 的 pathspec 边界有缝，`-f` 可能把 SQLite/audit/持仓/密钥强行提交进 `.hermes`，正好打破审计 S8 的修复。

**怎么验**：
```bash
# 真实那次部署 commit 到底提交了哪些文件（必须只有 allowlist，0 运行态）
git -C ~/.hermes diff-tree --no-commit-id --name-only -r 0722e78
git -C ~/.hermes diff-tree --no-commit-id --name-only -r 0722e78 \
  | grep -ciE '\.sqlite|audit_log|/data/|order|position|\.tar\.gz|backup|token|key|config'   # 必须 0
# 看 deploy_git_pathspecs 的 :(exclude) 是否真的挡住 data/config/tests
sed -n '/deploy_git_pathspecs/,/^}/p' scripts/deploy_to_live.sh
```

**构造反例（关键）**：在 `test_deploy_to_live.py` 的 fixture 里，往 `package/data/` 和 `package/config/` 各放一个 `.py`（会被 `:(glob)**/*.py` 匹配），跑成功用例，**断言它们不在 commit 集合里**。若 `-f` 把 `data/**.py` 或 `config/**.py` 提交了，`:(exclude)` 边界就是破的 → P1。

**应有测试**：现成 `test_isolated_success_reaches_single_success_exit` 已断言 commit 集合是精确白名单（不含 `data/soft_history/runtime.csv`）。请加 `.py`-under-data/config 的反例强化它。

### 3.2 verify_live 的 receipt-污染检查：现在是真跑还是仍有洞？

**改动**：`ops/verify_live.sh:93` 把 `tail -n +$((MARK + 1)) "$LOG" | grep ...` 改成 `grep -qE "\[receipt\]|state committed" "$LOG"`（`MARK` 从未赋值，`set -u` 下原本被短路成「未污染」=假通过）。

**为什么危险**：这是「verify 没有偷偷写官方 receipt/state」的唯一守卫。修之前它**根本没在检**。修之后要确认它**真能抓到污染**，且不会误报。

**怎么验 + 构造反例**：
```bash
# (a) 抓真污染：造一个含 [receipt] 的日志，确认检查判 FAIL
#     在隔离 fixture 下让 run_daily.sh 的输出里出现 "[receipt]" 或 "state committed"，
#     断言 verify_live 退非零。（修之前它会假"untouched"通过。）
# (b) 不误报：看这次成功 verify 的真实日志里到底有没有这两个串
grep -nE "\[receipt\]|state committed" /tmp/deploy_r1r5_v2.log || echo "clean run 里确实没有这两个串（说明 PASS 是真的）"
# (c) 确认 MARK 已无残留
grep -n "MARK" ops/verify_live.sh   # 应为空
```

**应有测试**：`test_ops_entrypoints.py` 应加一条：verify_live 跑在「日志含 `[receipt]`」的隔离 fixture 下必须 FAIL。目前可能只测了 PASS 路径。

### 3.3 fixture 回归护栏是真的吗？

**改动**：`test_deploy_to_live.py` 的 fixture 现在写 `~/.hermes/.gitignore`（`bin/`+`tests/`），让成功用例必须 `-f` 才过。

**构造反例（必做）**：
```bash
# 临时把 deploy_to_live.sh 的 `git add -f` 改回 `git add`，跑成功用例，必须 FAIL；再改回来。
# 若改回 git add 后用例仍 PASS → 护栏是假的 → P2。
```

### 3.4 [我动了 live] 首次失败 + 回滚有没有留残渣？live 是不是恰好等于新代码？

**怎么验**：
```bash
L=~/.hermes/skills/investment/escape-top/hermes_escape_top
cat $L/VERSION                                   # 71e939c 20260619_225659
grep -c assert_pipeline_lease $L/core/safe_io.py # 2（新码在）
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8766/   # 200
# live 包 .py 树 == repo src .py 树（排除 tests/data/config）—— 任何 drift = 部署/回滚留了脏东西
diff <(cd $L && find . -name '*.py' -not -path './tests/*' -not -path './data/*' | sort) \
     <(cd ~/Documents/github/hermes/src/hermes_escape_top && find . -name '*.py' -not -path './tests/*' -not -path './data/*' | sort)
# 官方 receipt 没被两次 verify 污染（仍是当天 scheduled，不是 manual_rerun）
/usr/bin/python3 -c "import json;r=json.load(open('$L/data/archive/run_receipt.json'));print(r.get('run_type'),r.get('run_id'))"
# 备份目录里应有 2 个 predeploy backup（每次部署各一），它们是 .hermes git 之外
ls -la ~/.hermes-deploy-backups/escape-top/
```
**反例**：上面的 `.py` 树 diff 非空、或 receipt `run_type != scheduled`、或 live 出现 `522fa16` 残留 → P1。

### 3.5 CSV 权限归一化：内容真没变？范围对吗？

**怎么验**：
```bash
L=~/.hermes/skills/investment/escape-top/hermes_escape_top
find $L/data -name '*.csv' -perm 600 | wc -l    # 0（无残留 0600）
# 抽查：拿记录里某文件的 before-sha 和当前 sha 比（应一致——只改了 mode）
sed -n '5,15p' building/reports/csv_perms_normalization_2026-06-19.md
# 确认 chmod 只碰了 data 下的 .csv、没误伤别的（记录里 49 行应全是 data/**.csv）
```
**反例**：记录里出现非 `.csv` 或 `data/` 外路径、或某文件 before≠after sha → P2。

### 3.6 config 答 N 是否安全（use_indicator_cache 漂移）

部署对 `Apply repo config?` 答 **N** → live config **缺** `use_indicator_cache`。验证：`market.py:106` 用 `.get("features",{}).get("use_indicator_cache", False)` → 缺键默认 `False` == 等价回放里测的值。请确认 live 缺这个键时跑分正常、且不是隐藏的 flag 翻转。

---

## 4. 独立复核命令

```bash
cd ~/Documents/github/hermes
git status --short; git diff --check
bash -n scripts/deploy_to_live.sh ops/verify_live.sh
# 全套 + 部署/ops（venv 与生产一致性也看）
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python \
  -m pytest src/hermes_escape_top/tests -q            # 期望 562 passed, 1 warning
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python \
  -m pytest src/hermes_escape_top/tests/test_deploy_to_live.py \
            src/hermes_escape_top/tests/test_ops_entrypoints.py -q   # 期望 19 passed
```
**复审中禁止**：跑真实 `deploy_to_live.sh`、chmod live、commit/push。所有部署测试用 tmp fixture。

---

## 5. 已知残余 / 我没做的

- **3 个交易日观察**（未做，被动）：下一个 07:10 是新代码首次生产 daily。盯：每天仅一份 scheduled official、receipt/state/audit `run_id` 一致、无 200-BUSY、无陈旧绿回执、repo/`.hermes` 无运行态脏文件、无锁 timeout。
- **R6**（versioned release + symlink 原子切换）：稳定 3 天后另开，未做。
- **config 仍是交互式 `read`**（B-5 本应改 env 驱动，未改）：本次靠 `echo N` 喂；若以后部署在无 tty 下跑要确认 EOF→N 的默认仍安全。
- `/private/tmp/hermes-baseline-3f48dd3` worktree 是等价比较器基线，保留。

---

## 6. 严重度与回报格式

| 等级 | 定义 |
|---|---|
| P0 | live 可下单 / readonly 被改 / 真实持仓·密钥损坏 |
| P1 | `.hermes` 混入运行态、verify 污染没被抓、live 残留/drift、回滚不精确 |
| P2 | 护栏是假的、权限记录不实、检查误报/漏报 |
| P3 | 文档漂移、诊断性问题 |

请先列 findings（按 P0–P3，每条带 文件:行 + 可触发场景 + 现有测试为何没抓 + 最小修复 + 应加的失败测试）。无阻断项则明确写：
```
未发现 P0/P1/P2。
已运行：<命令/结果>
live 状态核对：VERSION / 8766 / receipt / .py-tree-diff / CSV-perms
残余风险：<list>
结论：APPROVE / CHANGES REQUESTED
```
