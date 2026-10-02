# urllib3 安全维护：第一批交接与外审指南

日期：2026-10-02，北京时间。基线：`hermes-docs @ 2db0cdc`；候选：当前未提交工作树。

## 范围

唯一实现改动是 `requirements.lock` 的 urllib3 版本及 wheel/sdist 两个哈希：2.7.0 → 2.8.0，三行替换。另新增本交接文档。

其他 31 个生产依赖的版本、哈希均未变；requirements.txt、生产 Python、配置、flags、评分、路由、准入、身份、修订预算、部署脚本均未改。三份九月未跟踪计划文件不属本批，不得顺手提交。

只完成第一批。A2 历史版本等后续工程未启动。截至外审取证时本批未提交、推送或部署；后续提交状态以 Git 为准。用户随后授权继续收口，仅提交/推送，未授权本批直接部署；live 依赖未因本地修复而升级。

## 原问题与风险边界

上一轮同一基线依赖扫描返回非零，urllib3 2.7.0 命中：

- PYSEC-2026-4175：HTTPS 代理 TLS 配置可能被忽略或覆盖。
- PYSEC-2026-4176：chunked Deflate 解码可能无限循环。
- PYSEC-2026-4177：流式 chunk-size 行可能无界缓冲。

修复版本均为 2.8.0。参照 [urllib3 官方 2.8.0 公告](https://urllib3.readthedocs.io/en/stable/changelog.html)。本轮从 [PyPI 2.8.0 元数据](https://pypi.org/pypi/urllib3/2.8.0/json) 核对版本、Python >=3.10、未撤回状态及发行物 SHA256。

有依赖漏洞不等于已经证明 Hermes 全部路径可被利用；没有检查线上代理配置或进行生产攻击复现。下面只独立复现第三条的行为差异，另外两条依靠修复发行版和漏洞数据库检查，不能声称全部攻击场景均已复现。

官方公告另提示兼容性行为变更：依赖“目标 TLS 设置覆盖 HTTPS 代理 TLS 设置”的配置需要调整，代理 CA/客户端证书应使用 proxy_ssl_context，代理身份校验使用 proxy_assert_hostname/proxy_assert_fingerprint。本轮源码检索未发现生产路径自定义这些代理 TLS 设置；已有安全测试禁止关闭证书校验。但未检查 live 环境代理变量或外部包装器，不能据此宣称所有部署环境均无影响。

## 修改方法与锁定证据

使用现有 uv compile 工作流，在临时文件基于原 lock 定向更新。**必须先复制基线 lock 到输出文件作为已有版本种子，再定向升级；不是向一个全新的空输出文件解析。** 原始运行使用 uv 0.11.7（9d177269e），Python 目标 3.11。

```sh
# BASELINE_LOCK 必须先验证为下表基线 SHA；可由 git show 2db0cdc:requirements.lock 取得。
cp "$BASELINE_LOCK" /tmp/hermes-urllib3-20261002.lock
uv pip compile requirements.txt --generate-hashes --python-version 3.11 \
  --upgrade-package urllib3==2.8.0 \
  --output-file /tmp/hermes-urllib3-20261002.lock
```

生成当时的临时输出与仓库候选逐行一致，仅生成命令中的临时 output 路径不同；仓库保留原通用生成注释。没有手工猜测哈希或解析器升级其他包。这是有输入种子的生成证据，不是承诺任意时刻无约束重新解析都产出同一 lock。

外审无种子重解析得到另 11 个传递依赖升级，属于不同解析输入/上游可用版本造成的漂移，不证明候选污染。收到反馈后，独立验证基线 SHA、复制到新输出路径，再按上述定向命令重跑，结果仍与候选正文逐字一致（只排除生成 header 的输出路径）。后续审核主要验证候选固定 SHA、发行物哈希与真实按锁安装；不要把无种子重新解析当作候选有效性的门槛。

| 对象 | SHA256 |
|---|---|
| 基线 requirements.lock | c5cd01673b672446f9bcb12644fba423bc8a88c7613f3a25dde4197a827f69b2 |
| 候选 requirements.lock | 2da2dfa2c73aaa68037fedf5aaa918f9f2c166ef960ec922b4bd963aed10886e |
| 原始临时生成文件（含其 output 路径 header） | d02380a0578b6e2c2c11e4afa1d15db955d1af70104cdc5baeb564b581d05e76 |
| urllib3 wheel | 0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3 |
| urllib3 sdist | 63bf2ead4c879426ebf22ef2a781eeb4aa3b4ae798a0435506f8687fd5bb9b63 |

临时文件指纹是本次生成的辅助绑定，不是永久归档或签名；外审不得依赖 /tmp 文件长期存在。仓库候选本体、基线 Git 对象与公开发行物才是持续复核依据。

真实 `ops/bootstrap_runtime.sh` 在 `/tmp/hermes-urllib3-runtime-20261002` 构建候选 SHA 命名环境，使用 `--require-hashes` 安装全部 32 包，导入/SSL 验证通过；再次调用返回同一路径，复用验证通过。没有在该不可变运行环境中追加 dev 工具。

测试另用 `/tmp/hermes-urllib3-tests-20261002`：先按 lock/hash 安装，再以 lock 为 constraint 安装 dev extras，避免工具安装改掉生产依赖。Python 3.11.15、NumPy 2.0.2、SciPy 1.13.1、requests 2.33.0、urllib3 2.8.0。

## 确定性漏洞行为探针

使用独立本机临时 HTTP 服务，随机端口；Session.trust_env=False，避免环境代理影响。无外部服务器、业务源、live 文件或 IBKR。70,000 字节 chunk 扩展足够超过新版限制，不需要耗尽内存。

结果：旧 2.7.0 接受，拒绝断言失败、退出 1；新 2.8.0 抛 `ChunkedEncodingError`，详情 `Response chunk size line exceeded maximum allowed length`，退出 0。

完整探针如下；外审可以在自己的隔离目录运行，不依赖作者临时脚本：

```python
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import requests
import urllib3

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            self.wfile.write(b"1;" + b"a" * 70000 + b"\r\nx\r\n0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass

with HTTPServer(("127.0.0.1", 0), Handler) as server:
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    rejected = False
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get(
                f"http://127.0.0.1:{server.server_port}/", stream=True, timeout=3
            ) as response:
                assert b"".join(response.iter_content(chunk_size=1)) == b"x"
    except requests.exceptions.ChunkedEncodingError:
        rejected = True
    finally:
        server.shutdown()
        thread.join(timeout=5)
    print(urllib3.__version__, rejected)
    assert rejected, "oversized chunk header must be rejected"
```

这验证发行版实际阻断路径，不等于新增了 Hermes 持续回归测试。已有 CI pip-audit 负责后续已知漏洞门禁；没有为第三方库添加生产分支。

## 验证结果

| 检查 | 结果 |
|---|---|
| lock 生成结果对账 | PASS；32 包，仅 urllib3 版本/hash 改变 |
| 真实 bootstrap_runtime 临时构建与复用 | PASS |
| 运行环境兼容 | 32 packages compatible |
| 测试环境兼容 | 62 packages compatible |
| 采集/见证/入口 focused | 132 passed，15.78s |
| 全套 | 1481 passed，199.19s；候选新环境、合成 FRED key、隔离数据 |
| 治理 | 8/8 OK，ibkr_readonly=true |
| pip-audit 候选 lock | No known vulnerabilities found，退出 0 |
| 漏洞行为探针 | 旧版断言失败，新版拒绝并通过 |
| diff whitespace | PASS |

pip-audit 仍输出两条工具提示：建议完整哈希锁定、使用锁生成器。这不是漏洞告警；本文件已经全包哈希锁定并由 uv 生成，真实安装启用了 --require-hashes。保留提示，不把输出描述为完全无 warning。

## 独立外审步骤

1. 确认范围只有 lock 三行及本文；三份九月计划不计入，不修改或提交。
2. 独立核对基线/候选固定 SHA，从官方元数据重算 wheel/sdist 哈希，解析两份已有 lock，确认其他 31 包不变。生成文件存在时可核验其指纹/正文，但不依赖作者临时目录。不要用无种子重新解析验证候选；若审核生成流程，须先以基线 SHA 校验过的 lock 作为输出种子，保留 --upgrade-package urllib3==2.8.0，单独记录工具版本及重解析差异。
3. 在全新临时根运行 bootstrap_runtime，确认目录名等于候选 lock SHA；不要指向 live/runtime。
4. 在另一个隔离测试环境按哈希安装，用 lock constraint 安装 dev extras，执行 pip check 与候选 pip-audit。
5. 分别用基线和候选依赖运行上述本机探针；旧失败、新通过。不要访问 8766 或外部业务源。
6. 使用合成 FRED_API_KEY 跑 focused 和全套，再执行 governance；不要连接 IBKR、刷新数据、评分生产或运行 official daily。
7. 检查 config/评分/路由/身份/部署脚本无 diff，不使用 generated 文档代替直接证据。

实际测试命令以仓库为工作目录，解释器替换为审核者隔离环境：

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key <PY> -m pytest \
  src/hermes_escape_top/tests -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src <PY> \
  scripts/check_governance_consistency.py
<PY> -m pip_audit -r requirements.lock --no-deps --disable-pip \
  --progress-spinner off
```

没有重跑四日期比较器或全窗口回测，不能声称本批获得新的 strict 等价证据；此次只有 HTTP 依赖改变，全套与定点覆盖其兼容面，没有数值依赖升级。

## 发布与后续

独立外审已通过，实现可提交/推送；F1/F2 文档已修正并复核，按用户授权仅提交本批两文件、推送并核对 CI。外审结论不直接授权部署；仍须独立发布批准及常规门槛，保留 live config、无 writer、避开 07:00–07:20。新 lock 会触发新的 SHA 运行环境，不在旧 live venv 原地升级。不得为上线验证补跑 official。

补充接受项：bootstrap 依赖预先存在的 uv/Python 可执行文件，当前不钉定引导工具版本；长期跨机器可复现性另行治理。运行环境按 lock SHA 选择，回滚应选择旧 release 对应的旧 SHA 环境，不在候选环境内原地降级，也不手改 marker 绕过匹配。本批未演练发布回滚，更不声称 bootstrap 会修复同 SHA 目录中被人工篡改的全部依赖。

随后才进入 A2：完整 canonical 新旧版本存储与隔离恢复。它与本次依赖安全修复分开审查，避免扩大恢复边界的改动混入小维护。
