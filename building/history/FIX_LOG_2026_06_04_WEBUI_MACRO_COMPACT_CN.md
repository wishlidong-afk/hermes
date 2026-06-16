# Fix Log — 2026-06-04 WebUI 宏观 A 模块紧凑中文化

## 背景

用户反馈新版 8766 WebUI 中宏观 A 模块展示过大，要求精简、优化排列，并使用中文。

## 已完成

文件：

- `src/hermes_escape_top/web/render.py`
- `src/hermes_escape_top/tests/test_phase14_web.py`

改动：

- 标题改为中文：`宏观 A 模块评分`。
- 去掉英文标题 `A Macro Module`。
- 由“大分数框 + 全量表格”改为紧凑仪表排列：
  - A 模块总分
  - 避险阈值
  - 市场状态
  - QQQ 趋势
- 默认只展示 4 个主要宏观触发项。
- 全量 A 模块指标改为折叠区：`展开全部宏观 A 指标`。
- 窄屏下也保持 2 列，减少首屏高度。
- A 模块因子标题补齐中文映射，例如：
  - 市场宽度
  - QQQ 派发压力
  - VIX 低波动
  - NAAIM 仓位

## 本地验收

页面：

```text
http://localhost:8766/
```

确认：

```text
宏观 A 模块评分: true
A 模块总分: true
避险阈值: true
展开全部宏观 A 指标: true
A Macro Module: false
A3 COMPONENT: false
A8 QQQ: false
```

## 测试

Targeted tests:

```bash
PYTHONPATH=src python3 -m unittest \
  src/hermes_escape_top/tests/test_phase14_web.py \
  src/hermes_escape_top/tests/test_phase15_integration.py
```

结果：

```text
Ran 6 tests in 62.840s
OK
```

注：测试耗时仍受当前 IBKR Gateway/TWS read-only 超时影响，页面功能本身正常。

Full tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests -p 'test_*.py'
```

结果：

```text
Ran 320 tests in 256.372s
OK
```
