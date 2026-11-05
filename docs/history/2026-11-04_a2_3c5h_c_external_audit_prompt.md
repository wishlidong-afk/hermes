# A2 3C-5h-C 晨验只读接线：独立外审入口

日期：2026-11-04，Asia/Shanghai。**这是首次针对 C 片新字节的外审请求，不是外审报告、通过声明或额外审批轮次。DEPLOY HOLD；A2 OPEN；Phase B 未启动。**

请审查当前冻结候选，不修改仓库、源码、测试、旧文档、证据或 live。允许在 /tmp 建隔离环境、重建基线、执行离线测试和保存复算结果；禁止 stage/commit/push/deploy、安装或启动系统任务、运行正式 daily/晨验、刷新行情/外部源、连接或刷新 IBKR。tmp 测试里的实际评分/receipt fixture 不等于官方运行。

## 1. 唯一审计范围

仓库：/Users/liweishi/Documents/github/hermes；HEAD 为 `8d16ad8ba639341a38ca5c29e278d12b81bb8efe`，但增量基线不是 HEAD 的旧源码，而是 B + P2 修正的已审候选。

- 修改：`ops/morning_acceptance.py`，仅本片 105 行新增；1484 行，SHA `217857aa94632ba89db62db630864b56d231e1bc27dd371f9db022187b4698b9`。
- 新增：`src/hermes_escape_top/tests/test_morning_publication_observation.py`，329 行、37 用例，SHA `e42644e8726d783dbd3eb212e98459d4c3d9964222c9bc00755db40209331021`。
- 增量证据：`building/reports/a2_production_capture/2026-11-04/3c5h_morning_wiring/` 的 before/ops、slice.patch、25 项源码/依赖绑定、51 件证据；清单自身 SHA `a74e9de973493a6763026a33a4eadb8d6f54df3ae0f6bc0ff8505f9c63ec4d8e`。
- 权威交接：`docs/history/2026-11-04_a2_3c5h_c_morning_wiring_handoff.md`，SHA `23e2916dd873b710c2a71b5ab5e50c27c1d3b27ed21d35511f20b6acbe036b54`；合同为同目录 `2026-11-04_a2_3c5h_c_morning_wiring_contract.md`。
- 前置批准：同目录 `2026-11-04_a2_3c5h_b_external_audit_{report,followup}.md`。B/5g/producer 原字节未改，不把 B 的批准转借给 C。
- 主目录其他累积 A2、三份九月计划、旧包及私有 capture 均不属于本片总批准范围；不要把整个 git diff HEAD 当作此片增量。

旧 ops 为 `985c617d739b7e45dd9b77d4af3ada440f10e7c6cae6f27c87cbbd283660029d`。B 的 review_fix source-binding 中这一个 ops 依赖已被 C 有意改变，其余19项应仍匹配；各片51/33/24/22件冻结清单不能现场重写来消除差异。

## 2. 先审源，再核验声明

1. 清点范围，重算两个源码/行数、25源码依赖、51证据及清单自身；核对 before/patch，确认没有评分、身份、config/flag、比较器、依赖、CI、部署或旧测试变更。
2. 逐行审三模块装载：指定物理发布，不执行项目 __init__，不改 sys.path、不借用开发/旧模块；缺失/目录/链接拒绝，异常及重复调用清理私有命名空间。系统 Python -I/-S/-B 的实际解释器版本需如实报告。
3. 审快照时序：主 receipt/audit 读取前取摘要，辅助后复核发布/archive/字节及双方已有 run/capture 身份；不一致只能 UNKNOWN，不重试选有利 run。
4. 确认 receipt/audit 摘要只做本轮一致性，不自算 journal 摘要重锚；B/5g 验证及未知 schema/深 JSON 拒收未弱化。
5. 独立覆盖主 PASS/FAIL/PENDING × 辅助四状态；正式 FAILED 和辅助 OK 同时可见，原七 checks/readiness/认证与退出码不被升级。
6. 对照 JSON 与 Markdown：UNKNOWN、official_receipt_status、anchor_source 都不能丢失或推为正常；OK 不代表当前缓存、新鲜度或 IBKR 连通。
7. 独立运行真实 producer→receipt→B→晨验 tmp 测试，区别已有 fixture stub/include_ibkr=False 与自然官方样本；核对观察期间无新增网络、DB、写入或当前缓存读取。
8. 复现四文件关联、全套、治理和静态；记录完整 argv/源绑定，区分作者原日志、审计员独立执行及仅阅读，不将计数算式当测试输出。
9. 先审比较器源码，再按第3节重建 B 基线及已提交种子、核对摘要，然后独立四日期 OFF strict。比较器 src manifest 不覆盖 ops，不能借它证明晨验行为。
10. 核对遗留债、信任/并发/资源边界、CI预算与阶段门槛，如实给出三个独立判定。不得仅凭全绿测试批准安装/部署或 A2 闭合。

## 3. 不依赖作者旧快照的基线重建

从仓库根目录执行下面的 Python 内容（标准库即可）。它只验证材料、在新建临时目录复制已绑定的377个包文件及 before/ops，并从固定 Git 对象导出**数据**；不会用 HEAD 旧源码代替 B 前置，也不会读 live/共享 data。

先审该脚本、比较器和清单的定义；摘要不是签名，脚本输出也不是审计正确性的独立证明。若绑定不匹配就停止，不用最新文件、当前行情或更新清单兜底。此代码 SHA（含结尾LF）为 `1c38a1f9ba642d633701410d8b7fa8ce534db3fb13030c532f2ce23c2e3e721d`。

```python
"""Reconstruct the reviewed B code baseline and committed seed, never live data."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile

repo = Path.cwd().resolve()
packet = repo / 'building/reports/a2_production_capture/2026-11-04/3c5h_morning_wiring'
head = '8d16ad8ba639341a38ca5c29e278d12b81bb8efe'
manifest = json.loads((packet / 'SHA256SUMS.json').read_text())
assert hashlib.sha256((packet / 'SHA256SUMS.json').read_bytes()).hexdigest() == 'a74e9de973493a6763026a33a4eadb8d6f54df3ae0f6bc0ff8505f9c63ec4d8e'
for name, digest in manifest['files'].items():
    assert hashlib.sha256((packet / name).read_bytes()).hexdigest() == digest, name
binding = json.loads((packet / 'source-binding.json').read_text())
for entry in binding['implementation'] + binding['dependencies']:
    assert hashlib.sha256((repo / entry['path']).read_bytes()).hexdigest() == entry['sha256'], entry['path']
evidence = json.loads((packet / 'equivalence.json').read_text())
work = Path(tempfile.mkdtemp(prefix='hermes-5hc-audit-baseline-'))
baseline = work / 'baseline'
baseline.mkdir()
for entry in evidence['baseline_source_evidence']['files']:
    relative = PurePosixPath(entry['path'])
    assert not relative.is_absolute() and '..' not in relative.parts and entry['kind'] == 'file'
    source = repo / relative
    assert not source.is_symlink() and hashlib.sha256(source.read_bytes()).hexdigest() == entry['sha256']
    target = baseline / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
ops = baseline / 'ops/morning_acceptance.py'
ops.parent.mkdir()
ops.write_bytes((packet / 'before/ops/morning_acceptance.py').read_bytes())
archive_command = ['git', 'archive', head, 'src/hermes_escape_top/data']
raw = subprocess.check_output(archive_command, cwd=repo)
with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
    for member in archive:
        if member.isdir():
            continue
        relative = PurePosixPath(member.name)
        assert not relative.is_absolute() and '..' not in relative.parts and member.isfile()
        relative.relative_to('src/hermes_escape_top/data')
        target = baseline / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.extractfile(member).read())
spec = importlib.util.spec_from_file_location('audit_comparator', repo / 'scripts/compare_pipeline_persistence.py')
comparator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparator)
fingerprint = comparator._tree_fingerprint(baseline, relative_roots=comparator.SOURCE_FINGERPRINT_ROOTS,
    excluded_prefixes=comparator.SOURCE_FINGERPRINT_EXCLUDES)
seed = baseline / 'src/hermes_escape_top/data'
seed_fingerprint = comparator._tree_fingerprint(seed, relative_roots=(*comparator.SEED_SUBDIRS, 'sentiment.xls'))
assert fingerprint['manifest_sha256'] == evidence['baseline_source_evidence']['manifest_sha256']
assert seed_fingerprint['manifest_sha256'] == evidence['seed_evidence']['manifest_sha256']
print(json.dumps({'status': 'PASS_PREPARATION_ONLY', 'baseline': str(baseline), 'seed': str(seed),
    'baseline_files': fingerprint['file_count'], 'baseline_manifest_sha256': fingerprint['manifest_sha256'],
    'seed_files': seed_fingerprint['file_count'], 'seed_manifest_sha256': seed_fingerprint['manifest_sha256'],
    'archive_command': archive_command, 'ops_before_sha256': hashlib.sha256(ops.read_bytes()).hexdigest(),
    'reconstructed_without_authors_old_snapshot': True}, indent=2))
```

预期：基线377/`24f37156178f8e5953e2534f7502b21af8a7a588cd8bc3c9fd1da5eda5356806`，种子57/`8557342fc9b34ecab5670c0770bfc6d92edcf1cff0ae6cdbf356097c86caeb11`，ops旧摘要985c617d...。输出的 baseline/seed 是本次新目录，不是永久路径。

审计解释器独立准备并记录版本；原环境 Python3.11.15、Ruff0.15.22、mypy2.3.0、NumPy2.0.2/SciPy1.13.1。完整命令以包内 verification-runs.json 为参照；允许替换解释器、cache/basetemp和输出目录，不改验证契约、源码、忽略集或测试成员。

关联测试的准确四文件命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests FRED_API_KEY=external-audit-synthetic-key \
  "$PYTHON" -B -m pytest \
  src/hermes_escape_top/tests/test_morning_acceptance.py \
  src/hermes_escape_top/tests/test_transaction_v2_acceptance.py \
  src/hermes_escape_top/tests/test_scheduled_broker_publication.py \
  src/hermes_escape_top/tests/test_morning_publication_observation.py \
  -q -p no:cacheprovider
```

四日期命令中的 BASELINE/SEED 用上一步输出，PYTHON为审计解释器，OUTPUT为tmp内新报告，不覆盖冻结证据：

```bash
PYTHONDONTWRITEBYTECODE=1 FRED_API_KEY=external-audit-synthetic-key \
  "$PYTHON" -B scripts/compare_pipeline_persistence.py \
  --baseline-source "$BASELINE" --candidate-source "$PWD" --seed-data "$SEED" \
  --python "$PYTHON" --contract strict \
  --baseline-label 3c5h-B-publicly-reconstructed --candidate-label 3c5h-C-audit \
  --output "$OUTPUT" \
  --as-of 2022-01-03 --as-of 2022-01-25 --as-of 2026-05-29 --as-of 2026-06-04
```

全套命令同样带 PYTHONDONTWRITEBYTECODE、合成FRED key和PYTHONPATH，执行 `"$PYTHON" -B -m pytest src/hermes_escape_top/tests -q -p no:cacheprovider`。15文件mypy的完整成员在 verification-runs.json；扩大的 ops 检查预期仍有4条既有消息，须与before逐字归一化对照，不能冒称全文件清零。compileall如需执行，PYTHONPYCACHEPREFIX必须指向tmp，避免写入仓库缓存。

## 4. 作者声明与本轮入口复核的归属

冻结候选作者结果：37新、明确四文件182关联、2179全套（1421.17s）、治理8/8、原15文件mypy与Ruff门禁、四日期OFF strict通过。ops单文件mypy前后4条未清零；producer既有15类型/19Ruff债另列。CI未运行，本地23分41秒不能冒充20分钟预算的云端绿。

内部复核记录不是外审；其19定点命令有记录，12组内联before对照没有单独保存探针/日志摘要，只能作为补充证言。性能诊断是本机夹具，不能外推实时缓存/自然运行/长期audit增长。

2026-11-04 作者另做了**新目录重建演练**：上述脚本退出0，基线377/24f37156...、种子57/8557342f...匹配；在该新基线上实际运行四日期strict，退出0/24.13s，4/4空差异、四日期两侧input_hash与原报告一致。新报告SHA `6a01caefb9a451375c51c1516a3723c1d236675240449b0936c71c9864cdcd36`。这是作者验证外审入口，不是外审员独立复算或新全套运行；原51件与旧交接均未改写。

该演练的命令/输出存于仓库外 `/Users/liweishi/Documents/New project/hermes-a2-5hc-audit-entry-2026-11-04/`，不用它的临时目录当外审前置；本节代码可独立重新准备。缺失私有记录不应被误说成冻结包缺文件。

## 5. 要求返回的结论

请报告 P0→P3、逐项证据与准确文件行号，并分别判定：

- C 片及其指定前置交互的代码正确性。
- 是否允许精确增量提交/推送，哪些前置/证据/文档应分列；不能批准整棵dirty tree或使用git add -A。
- 系统脚本安装、R6部署与A2闭合是否具备；必须保留尚未满足的A1发布/迁移/旧writer回滚、CI与自然ON/v2样本等门槛。

当前仍无用户 Git/安装/部署授权，真实系统任务继续运行原独立libexec脚本。恢复PASS不是根因修复证明，运行通过不等于A1/A2闭合。请勿以本次外审代替完整自动T1→T2、hermetic、断电/耐久性等未完成事项。**DEPLOY HOLD；A2 OPEN；Phase B not started。**

