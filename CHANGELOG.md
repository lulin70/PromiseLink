# Changelog

All notable changes to EventLink will be documented in this file.

## [0.2.0] - 2026-06-06

### Added
- **Phase 1 Backend Complete**: 7项Phase 1后端功能全部完成
  - F-55 DependencyAnalyzer（依赖性全图谱分析）
  - F-56 ContextMatcher（场景Event驱动匹配）
  - F-57 SemanticSearch（向量化语义搜索引擎）
  - F-58 Association Enhancement（关联发现增强）
  - PriorityScorerV2（四维动态优先级：紧急度×0.4 + 重要度×0.6）
  - Implicit Feedback Collector（隐式反馈学习）
  - Insight Engine API端点
- **DataSourceAdapter**: 抽象数据接入层（Manual/Voice/WeChat/CSV/Email）
- **NLG Service**: 自然语言生成服务（Event标题、关系简报、Todo描述）
- **Email Adapter**: 邮件同步适配器（Phase 1）
- **Voice Query Service**: 语音查询服务
- **WeChat Forward Adapter**: 微信转发适配器
- **EmbeddingProvider**: 向量嵌入提供者（API→local fallback双模式）
- **Resource Overuse Detector**: 资源过度使用检测
- **CarryMem Integration**: 协议接口 + NullMemoryProvider优雅降级
- **Security**: 字段级加密（concern/capability）+ 行级安全策略 + HMAC-SHA256持久化
- **Models**: voice_session, vector_embeddings, score_audit_logs, adapter_configs
- **APIs**: 17个端点（health/events/entities/todos/associations/relationship_briefs/dashboard/voice/import/export/demand/auth/wechat_forward/email_sync)
- **Tests**: 654测试用例 / 72%覆盖率 / 41个测试文件

### Changed
- Pipeline 重编号为14步（含Step 5.5语义搜索、Step 8.3资源过检、Step 8.5动态评分）
- Event.title 改为可选字段（默认"未命名"，NLG自动生成）
- Todo模型新增 completed_rank, dynamic_score, score_calculated_at 字段
- Person.properties JSONB支持 concern/capability混合模式
- PRD v4.0 → v4.7（向量化语义能力+智能定义+隐式反馈+数据接入层）
- 技术设计 v2.0 → v2.8（Insight Engine+DataSourceAdapter+向量语义）

### Fixed
- association_discovery: concern/capability兼容dict列表格式(F-53)
- relationship_brief_service: evidence属性访问修复+关联去重
- brief跨事件进度卡'unknown'值修复
- demo脚本DB清理路径修正+user_id过滤
- NLG service: 从硬编码响应改为Pipeline生成+系统NLG
- Pydantic V2 ConfigDict迁移准备

### Stats
- 654 tests passed, 0 failed | 72% coverage
- 28 service modules | 17 API endpoints | 6 data models
- Software version: 0.1.0 (init) → 0.2.0 (POC complete)

---

## [0.1.0] - Initial Release

### Added
- FastAPI project scaffold
- Database models (entity, event, todo, association)
- Basic APIs (Health + Events CRUD)
- Docker configuration
- 8 detailed design documents (Database/API/Algorithm/Integration/UI_UX/Security/Test_Plan/Deployment)
- PRD v4.0 (relationship management core loop)
- Technical design v2.0
