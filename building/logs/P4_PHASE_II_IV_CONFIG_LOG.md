# P4 Phase II–IV 配置与上线计划执行日志

更新时间：2026-06-01

## 目标

为 Phase II–IV 的分阶段上线提供：
1. 统一配置文件（所有引擎参数的单一事实源）
2. Feature flag 体系（逐步开启，默认全关）
3. Phase II/III/IV 各自的 override 配置
4. Scaler 迁移指南
5. 完整的上线计划和回退策略

## 已完成

### 1. 统一配置 `config/integration_config.py`

- `default_integration_config()`：包含全部 13 个配置段
  - symbols, sleeve_caps, thresholds (NEXT-3 v2)
  - confidence, risk_engine, sizing, governance, validation
  - drift, regime, sanitize, leader_map
  - features（全部 OFF）
  - calibration_ref, data_manifest_ref

- `phase_ii_overrides()`：启用 risk_engine + confidence + context + drift
- `phase_iii_overrides()`：追加 sizing_optimizer + governance
- `phase_iv_overrides()`：追加 validation + factor_calibration

### 2. 测试（5 个）

- 所有配置段存在
- 所有 feature flag 默认 OFF
- 阈值与 NEXT-3 v2 一致
- Phase II 不启用 sizing
- Phase III 启用 sizing + governance
- Phase IV 全启用但 meta_label 仍 OFF

### 3. 上线计划 `PHASE_II_IV_ROLLOUT_PLAN.md`

- Phase II: Shadow 对照（3-5 交易日）
- Phase III: 旧 scaler 替换 + 并排回测（2-3 天）
- Phase IV: 全验证套件 + 7 闸通过（3-5 天）
- 每阶段有明确验收标准和回退策略

### 4. Scaler 迁移指南 `SCALER_MIGRATION_GUIDE.md`

- 搜索 → 替换 → 验证 → 无残留检查
- 对照回测规范（Calmar/MaxDD/Turnover 不退化）
- 回退方案

## 当前状态

P4 Phase 0–I 地基 + Pipeline + Phase II–IV 计划 **全部完成**。
