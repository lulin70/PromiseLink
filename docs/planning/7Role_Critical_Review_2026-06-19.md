# PromiseLink P1-P9 7角色批判性评审报告

**评审日期**: 2026-06-19
**评审方法**: 实际代码验证 + 测试运行 + 文档交叉核对（非接受自评）
**评审范围**: /Users/lin/trae_projects/PromiseLink（基础版公开repo）
**关键说明**: 本次评审以实际命令运行为准，发现上一轮《7Role_ReReview_Consensus》报告存在多处数据不实。

## 总体评分：72/100 → 78/100（测试增强后）

> 初始评审72分，经补充83个用户旅程测试后提升至78分。主要扣分项：mypy 98错误（自评称0）、覆盖率69%低于80%目标、E2E测试名不副实、评审对象错位。

## 各角色评分

| 角色 | 初始评分 | 增强后评分 | 状态 | 与自评差异 |
|------|----------|-----------|------|-----------|
| PM | 80 | 80 | ⚠️ | 自评92，下调12 |
| 架构师 | 78 | 78 | ⚠️ | 自评90，下调12 |
| 安全 | 72 | 72 | ⚠️ | 自评88，下调16 |
| 测试 | 65 | 75 | ⚠️ | 自评87，下调12（测试增强后提升10分） |
| 开发 | 70 | 70 | ⚠️ | 自评89，下调19 |
| DevOps | 75 | 75 | ⚠️ | 自评90，下调15 |
| UI | 80 | 80 | ⚠️ | 自评88，下调8 |

## 阻断项（B级，必须修复才能进入P10）

- **B1: mypy类型检查98错误，自评报告与CHANGELOG均称"0 errors"严重不实**
  - 影响：CI的mypy步骤实际会失败，但自评报告声称CI全绿
  - 证据：`python -m mypy src/promiselink --ignore-missing-imports` → "Found 98 errors in 27 files"
  - 建议：修复98处类型标注，或如实记录mypy状态

- **B2: 测试覆盖率69%，低于80%目标，CI阈值仅60%**
  - 影响：relay_client.py（341行）0%覆盖率、title_generator.py 25%
  - 证据：实际pytest运行 → "TOTAL 8837 2729 69%"
  - 建议：补充relay_client/title_generator测试；将CI阈值提升至75%

- **B3: 评审对象错位——B1(admin双因素认证)等修复在已迁移的gateway/中，不在基础版repo**
  - 影响：ReReview报告的B1/B2/B3/B5/B6/B7/B8等修复验证引用gateway/，但已迁移到Pro repo
  - 建议：基础版与专业版应分别独立评审

- **B4: 前端CI的eslint步骤会失败——package.json无eslint依赖**
  - 影响：CI frontend job运行`npx eslint src/`，但无eslint依赖
  - 建议：添加eslint依赖或移除CI该步骤

## 改进项（I级，建议修复）

- I1: PRD版本号三处不一致（v5.2/v5.3/v5.4）
- I2: 测试数量虚报——ReReview称1577 passed含gateway/tests 235，实际本repo 1260 passed
- I3: tests/e2e/目录为空，E2E测试名不副实
- I4: bandit安全扫描非阻断（CI `|| true`）
- I5: test-pro CI job冗余（pro代码已迁移）
- I6: 30处bare except/except Exception散落API层
- I7: 文档版本漂移（Security_Design v3.1引用PRD v4.3）
- I8: 前端版本0.5.2与后端0.6.0不一致
- I9: 无staging环境实际部署
- I10: 监控告警未实际部署

## 测试增强成果（本次评审后执行）

### 新增83个用户旅程测试

| 功能 | 测试文件 | 测试数 | 覆盖缺口 |
|------|---------|--------|---------|
| 会后记录 | test_event_recording_enhanced.py | 31 | 9个缺口（email/wechat_forward事件类型、批量创建、retry/accept-degraded、500KB限制、级联删除、搜索过滤） |
| 待办生成 | test_todo_generation_enhanced.py | 23 | 8个缺口（_rule_based_fallback、_is_duplicate_todo、help类型、call事件、PriorityScorerV2、会话截断、LLM异常处理、去重集成） |
| 承诺跟进 | test_promise_followup_enhanced.py | 29 | 10个缺口（nudge-draft端点、their_promise生命周期、overdue/broken状态、安全约束、pending重置、fulfilled_at验证、草稿缓存、统计、双向承诺E2E） |

### 测试覆盖维度达标

| 维度 | 要求 | 实际 | 状态 |
|------|------|------|------|
| Happy Path | ≥50% | 62% | ✅ |
| Error Case | ≥15% | 18% | ✅ |
| Boundary | ≥10% | 20% | ✅ |

### 发现的源代码Bug（报告未修改）

**Bug: overdue_notified_at字段从未被API设置**
- 位置：src/promiselink/api/v1/promises.py 第179-183行
- 现象：PATCH /promises/{id}/fulfillment在overdue时未设置overdue_notified_at字段
- 影响：该字段始终为None
- 可能解释：可能设计为由后台通知任务填充，非手动API设置

## P10准入结论

- [ ] **不准入P10部署发布**

**理由**：存在4项阻断项（B1-B4）未解决：
1. mypy 98错误且自评虚报0错误
2. 覆盖率69%低于80%目标，关键模块relay_client 0%覆盖
3. 评审对象错位，B1等修复在Pro repo非基础版
4. 前端CI eslint会失败

**建议路径**：
1. 如实修复mypy 98错误（或调整mypy配置并诚实记录）
2. 补充relay_client.py/title_generator.py测试，覆盖率提至75%+
3. 基础版独立重新评审，剥离Pro repo内容
4. 修复前端CI（添加eslint依赖或移除该步骤）
5. 完成至少一次staging环境实际部署验证
6. 发布前执行真实E2E（起服务器+模拟许总的一天核心链路）

**关键警示**：上一轮ReReview报告（89/100通过）存在系统性数据不实——mypy错误数、测试通过数、E2E覆盖、评审对象均与实际不符。建议建立"评审数据必须附实际命令输出"的机制，杜绝自评虚报。测试的目的是系统健壮性，0%覆盖的relay_client.py恰恰是最该被测试的容错模块。

## 评审证据索引

- 实际测试结果：`pytest tests/` → 1260 passed, 45 skipped, 覆盖率69%
- mypy实际结果：`mypy src/promiselink` → 98 errors in 27 files
- ruff实际结果：All checks passed
- gateway/不存在：`ls gateway/` → No such file or directory
- CI配置：`.github/workflows/ci.yml`（bandit `|| true`第264行、cov-fail-under=60第62行）
- 前端依赖：`frontend/package.json`（无eslint、无test脚本）
- relay_client 0%覆盖：`src/promiselink/services/relay_client.py`（341行）
