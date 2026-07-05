# PromiseLink 详细设计文档

> **目录**: `docs/design/`
> **用途**: 存放详细设计文档、UI/UX设计、数据库设计、API设计等
> **最后更新**: 2026-07-05 (v0.8.0-rc2)

---

## 📋 文档清单（全部已完成 ✅）

| # | 文件名 | 版本 | 日期 | 状态 | 说明 |
|---|--------|------|------|------|------|
| 1 | **API_Design_v1.md** | v3.1 | 2026-06-11 | ✅ 生效 | Semantic Search API + Insight Engine API + DataSourceAdapter API + Media API + Privacy API + 前端集成 API |
| 2 | **Database_Design_v1.md** | v3.0 | 2026-06-11 | ✅ 生效 | 三级产品模型 + relay_connections + ai_usage_logs + 基础版/专业版/定制版 |
| 3 | **Algorithm_Design_v1.md** | v2.8 | 2026-06-07 | ✅ 生效 | DependencyAnalyzer + ContextMatcher + SemanticSearch + PriorityScorerV2 + 关联发现增强 |
| 4 | **Test_Plan_v1.md** | v5.1 | 2026-06-14 | ✅ 生效 | 托管PoC部署验证 + 23个新测试用例 + Media + Privacy + Rate Limiting |
| 5 | **Integration_Design_v1.md** | v2.9 | 2026-06-14 | ✅ 生效 | 托管PoC + 数字名片对接 + 语义搜索集成 + DataSourceAdapter + Media 服务 |
| 6 | **Deployment_Guide.md** | v0.5.0 | 2026-06-20 | ✅ 生效 | 向量存储部署 + sqlite-vec + pgcrypto + 监控指标 + Rate Limiting + nginx + HTTPS |
| 7 | **UI_UX_Design_v1.md** | v3.1 | 2026-06-14 | ✅ 生效 | 语义搜索UI + 依赖性展示 + 场景匹配 + 动态优先级 + 小程序前端集成 |
| 8 | **LLM_Prompt_Templates.md** | 0.4.1 | 2026-06-08 | ✅ 生效 | 语义搜索模板(24) + concern/capability提取(22) + Event标题生成(23) |
| 9 | **Security_Design_v1.md** | v3.1 | 2026-06-14 | ✅ 生效 | 向量数据安全 + 语义搜索安全 + Insight安全 + Adapter安全 + Rate Limiting + 前端安全 |
| 10 | **E2E_Full_Coverage_Plan_2026-07-03.md** | - | 2026-07-05 | ✅ 生效 | E2E 全覆盖计划 + Batch A-E 执行记录 + §8.10 零 skip 重写记录 |
| 11 | **PromiseLink_UX_Review_2026-07-05.md** | - | 2026-07-05 | ✅ 生效 | UX 评审报告 |

> **注**: 安全设计文档（Security_Design_v1.md 等）已随专业版迁移至 [PromiseLink-Pro](https://github.com/lulin70/PromiseLink-Pro) 私有仓库 `docs/archive/design/` 目录，基础版保留引用。

---

## 📐 设计原则

### 1. 数据库设计原则
- 基础版：SQLite 长期方案（per-user asyncio.Lock 序列化写）
- 索引策略：查询模式驱动，避免过度索引
- 数据加密：敏感字段 AES-256-GCM

### 2. API设计原则
- RESTful 风格，资源导向
- 版本管理：URL 版本号（/api/v1/）
- 响应格式：统一 JSON 结构 `{error: {code, message, details}}`
- 错误处理：5 层异常处理器（BusinessError / LLMError / PromiseLinkError / RequestValidationError / 兜底 Exception）
- 幂等性：PUT/DELETE 幂等，POST 非幂等

### 3. UI/UX设计原则
- 基础版：电脑宽屏两栏布局（≥1024px）
- 专业版：微信小程序手机竖屏窄版
- 莫兰迪色系（避免刺眼 emoji）
- 信息层级清晰（信息型 Todo vs 行动型 Todo）

### 4. 算法设计原则
- 置信度分级处理
- 人工确认机制（HITL）
- 可解释性（决策透明）
- 可撤回/回滚
- 性能优先（缓存 + 异步）

---

## 📚 相关文档

- 技术设计：`../architecture/PromiseLink_技术设计_v1.md` (v3.2)
- 产品需求：`../spec/PRD_v1.md` (v5.8)
- 项目状态：`../PROJECT_STATUS.md`
- 修复计划：`../spec/P0_P1_FIX_PLAN_2026-07-05.md`

---

## 📝 贡献指南

### 新增设计文档时请：
1. 遵循文件命名规范：`模块_设计类型_版本.md`
2. 包含版本号和变更历史
3. 提供清晰的图表和示例
4. 更新本 README 的文档清单
5. 关联相关的需求和技术设计
