# PromiseLink 文档一致性检查清单

> **更新时间**: 2026-06-20
> **阶段**: v0.6.3 基础版内部灰度就绪 — 三仓库独立（PromiseLink + PromiseLink-Pro + PromiseLink-miniapp）
> **目的**: 确认所有设计文档版本一致性，验证跨文档引用一致性

---

## 📋 一、文档版本一致性表

| # | 文档 | 路径 | 当前版本 | 更新日期 | 状态 |
|---|------|------|----------|----------|------|
| 1 | **PRD** | `spec/PRD_v1.md` | **v5.7** | 2026-06-20 | ✅ 生效 |
| 2 | **技术设计** | `architecture/PromiseLink_技术设计_v1.md` | **v3.2** | 2026-06-14 | ✅ 生效 |
| 3 | **数据库设计** | `design/Database_Design_v1.md` | **v3.0** | 2026-06-14 | ✅ 生效 |
| 4 | **API设计** | `design/API_Design_v1.md` | **v3.1** | 2026-06-14 | ✅ 生效 |
| 5 | **算法设计** | `design/Algorithm_Design_v1.md` | **v2.8** | 2026-06-08 | ✅ 生效 |
| 6 | **测试计划** | `design/Test_Plan_v1.md` | **v5.1** | 2026-06-14 | ✅ 生效 |
| 7 | **LLM Prompt模板** | `design/LLM_Prompt_Templates.md` | **0.4.1** | 2026-06-08 | ✅ 生效 |
| 8 | **集成设计** | `design/Integration_Design_v1.md` | **v2.9** | 2026-06-09 | ✅ 生效 |
| 9 | **部署指南** | `design/Deployment_Guide.md` | **v0.5.0** | 2026-06-20 | ✅ 生效（小程序路径已修正） |
| 10 | **UI/UX设计** | `design/UI_UX_Design_v1.md` | **v3.1** | 2026-06-14 | ✅ 生效 |
| 11 | **规格说明README** | `spec/README.md` | **v5.7** | 2026-06-20 | ✅ 同步 |
| 12 | **项目状态** | `PROJECT_STATUS.md` | **已同步** | 2026-06-20 | ✅ 最新 |
| 13 | **托管PoC Docker Compose** | `docker-compose.hosted-poc.yml` | **v1.0** | 2026-06-09 | ✅ 已验证 |
| 14 | **nginx配置** | `nginx/` | **v1.0** | 2026-06-09 | ✅ 已验证 |
| 15 | **PoC环境变量** | `.env.poc.hosted` | **v1.0** | 2026-06-09 | ✅ 已验证 |
| 16 | **部署脚本** | `scripts/ops/deploy-staging.sh` | **v1.0** | 2026-06-09 | ✅ 已验证 |
| 17 | **备份脚本** | `scripts/backup.sh` | **v1.0** | 2026-06-09 | ✅ 已验证 |
| 18 | **Prometheus配置** | `prometheus.yml` | **v1.0** | 2026-06-09 | ✅ 已验证 |

> **注**: 安全设计文档（Security_Design_v1.md、Security_威胁模型.md、Security_认证与API.md、Security_数据保护与主权.md、THREAT_MODEL.md）已随专业版迁移至 [PromiseLink-Pro](https://github.com/lulin70/PromiseLink-Pro) 私有仓库 `docs/archive/design/` 目录。

### 版本对照总结

- **需求层 (P1)**: PRD v5.7 ←→ 技术设计 v3.2（双主文档对齐）
- **设计层 (P3-P7)**: 集成设计 v2.9 / API设计 v3.1 / 测试计划 v5.1 / 算法设计 v2.8（安全设计系列已迁Pro）
- **部署层**: 部署指南 v0.5.0 / docker-compose.hosted-poc.yml v1.0 / nginx v1.0 / deploy-staging.sh v1.0 / backup.sh v1.0
- **运维层**: Prometheus配置 v1.0 / 备份脚本 v1.0
- **UI层**: UI/UX设计 v3.1（基础版宽屏H5；小程序UI独立仓库 PromiseLink-miniapp）

---

## 🔍 二、交叉引用一致性检查项

### 2.1 功能编号一致性

| 检查项 | 涉及文档 | 预期结果 | 状态 |
|--------|----------|----------|------|
| PRD功能编号 F-01~F-50 完整性 | PRD §4 | 50项功能全覆盖（含F-50语音助手）[F-50新增] | ⬜ 待确认 |
| 技术设计引用的功能编号与PRD一致 | 技术设计 §3~§7 | F-01~F-50 无遗漏/无多余 [F-50新增] | ⬜ 待确认 |
| API设计的端点覆盖P0功能 | API Design §3~§7 | F-01/F-02/F-03/F-04/F-06/F-44~F-48/F-50 有对应API [F-50新增] | ⬜ 待确认 |
| 测试计划的用例覆盖所有P0功能 | Test Plan §3 | 12项P0功能（含F-50）均有测试用例 [F-50新增] | ⬜ 待确认 |

**关键编号清单（P0核心）**:
```
F-01 事件语义路由    F-02 管线化实体抽取   F-03 实体归一(5步)
F-04 关联发现(8种)   F-05 商机匹配度(暂停) F-06 Todo生成追踪
F-44 Input Scope分类  F-45 Action Type识别  F-46 Todo降噪
F-47 RelationshipBrief  F-48 RelationshipStage
F-50 智能语音助手(NLU+语音会话+多轮对话) [F-50新增]
```

### 2.1.1 F-50 语音助手专项交叉引用检查 [F-50新增]

| 检查项 | 涉及文档 | 预期结果 | 状态 |
|--------|----------|----------|------|
| PRD v4.4的F-50是否在API_Design有对应端点 | PRD §4 ↔ API Design §3~§7 | POST /voice/sessions + GET /voice/sessions/{id} + WebSocket /voice/ws 存在 | ✅ 已确认 |
| Algorithm_Design的NLU章节是否与Integration_Design的Orchestrator一致 | Algorithm §5 ↔ Integration §4 | NLU意图分类器输出格式与Orchestrator输入格式匹配 | ✅ 已确认 |
| Database_Design的voice_sessions表字段是否与API_Design的VoiceSessionResponse一致 | DB Design §2 ↔ API Design §3 | session_id/user_id/status/intent_history/transcript 字段完全一致 | ✅ 已确认 |
| Test_Plan的44个用例是否覆盖所有P0意图 | Test Plan §3 ↔ PRD §4 | F-50的12个核心意图（查询关系/创建Todo/查看日程等）均有测试用例 | ✅ 已确认 |
| UI_UX_Design的无障碍规范是否符合许总需求 | UI/UX §3 ↔ PRD §1 | 语音交互WCAG 2.1 AA级合规 + 键盘导航支持 | ✅ 已确认 |

### 2.2 数据模型一致性

| 检查项 | 涉及文档 | 预期结果 | 状态 |
|--------|----------|----------|------|
| 数据库表结构与API请求/响应字段名一致 | DB Design ↔ API Design | 字段命名风格统一(snake_case) | ⬜ 待确认 |
| 核心实体属性定义一致 | DB §2 ↔ API §3 | entity/event/association/todo 字段完全匹配 | ⬜ 待确认 |
| 枚举值定义一致 | 所有设计文档 | todo_type/scope/action_type/relationship_stage 枚举值相同 | ⬜ 待确认 |

**核心枚举值速查**:
```python
# Todo类型 (6种)
TODO_TYPES = ["promise", "help", "care", "followup", "cooperation_signal", "risk"]

# Input Scope (8种)
INPUT_SCOPES = ["conversation", "meeting_notes", "business_card", "cooperation_file",
                "social_interaction", "resource_info", "feedback_record", "system_event"]

# Action Type (6种)
ACTION_TYPES = ["follow_up", "introduce", "collaborate", "provide_help",
                "seek_help", "risk_alert"]
```

### 2.3 安全规则一致性

| 检查项 | 涉及文档 | 预期结果 | 状态 |
|--------|----------|----------|------|
| PII字段列表与脱敏规则一致 | Security §3 ↔ API §8 | 手机号/邮箱/姓名脱敏方式相同 | ⬜ 待确认 |
| LLM输入消毒规则与Prompt模板约束一致 | Security §5 ↔ LLM_Prompt §0 | forbid/avoid规则对齐 | ⬜ 待确认 |
| 认证机制描述一致 | Security §2 ↔ API §2 | JWT + 临时授权码流程匹配 | ⬜ 待确认 |

### 2.4 算法与Prompt一致性

| 检查项 | 涉及文档 | 预期结果 | 状态 |
|--------|----------|----------|------|
| 匹配算法的六维权重与Prompt指令一致 | Algorithm §3 ↔ LLM_Prompt §2 | keyword(25%)+industry(20%)+topic(15%)+llm(10%)+history(10%)+callability(20%) | ⬜ 待确认 |
| 实体归一5步算法与抽取Prompt一致 | Algorithm §2 ↔ LLM_Prompt §1 | 归一逻辑与Prompt输出格式匹配 | ⬜ 待确认 |
| AI输出语言规则三铁律在所有AI相关文档中一致 | Algorithm §1 / LLM_Prompt §0 / Integration §3 / Test Plan §4 | 三条规则原文相同 | ⬜ 待确认 |

**AI输出语言规则三铁律**:
1. 推测必须标记（置信度 < 80% 时标注 `[推测]`）
2. 禁止自动判定资源（不主动将联系人标记为"可提供资源"）
3. 禁止建议索取资源（不主动建议用户向联系人索取资源）

### 2.5 部署配置一致性

| 检查项 | 涉及文件 | 预期结果 | 状态 |
|--------|----------|----------|------|
| Dockerfile与部署指南步骤一致 | 项目根目录 `Dockerfile` ↔ Deployment Guide §3 | 基础镜像/依赖安装/启动命令匹配 | ⬜ 待确认 |
| docker-compose.poc.yml服务定义完整 | `docker-compose.poc.yml` ↔ Deployment Guide §3.2 | web/db/redis三个服务配置齐全 | ⬜ 待确认 |
| docker-compose.hosted-poc.yml服务定义完整 | `docker-compose.hosted-poc.yml` ↔ 技术设计 §8.6.3a | api/nginx/certbot三个服务配置齐全 | ✅ 已确认 |
| 环境变量模板与代码config.py一致 | `.env.poc.hosted` ↔ `src/promiselink/config.py` | 必需环境变量全覆盖 | ✅ 已确认 |
| nginx配置与部署指南一致 | `nginx/` ↔ Deployment Guide §3 | 反向代理+HTTPS+certbot配置匹配 | ✅ 已确认 |
| 部署脚本可执行 | `scripts/ops/deploy-staging.sh` ↔ Deployment Guide | 一键部署流程完整 | ✅ 已确认 |
| 备份脚本可执行 | `scripts/backup.sh` ↔ Deployment Guide | PG dump+Redis AOF备份完整 | ✅ 已确认 |

---

## ⚠️ 三、已知遗留问题

### 3.1 文档完整性缺口

| 问题 | 影响 | 计划解决时间 | 负责人 |
|------|------|-------------|--------|
| **UI_UX_Design为简化版**，缺少详细交互流程图和组件规范 | 前端开发可能需要补充设计细节 | Phase 1 前由前端团队确定 | 前端负责人 |
| **F-05商机匹配功能暂停**（PoC阶段不做），但PRD和技术设计中仍有相关描述 | 开发时需注意跳过此功能实现 | Phase 2 恢复 | 产品+架构师 |
| **自建小程序为备选方案**（优先使用IAMHERE），集成设计中微信相关章节为占位 | 如需自建小程序需补充详细设计 | 视业务需求确定 | 移动端开发 |
| **Arch角色评审输出失败**（仅PM角色成功输出完整报告），Arch角色的架构评审要点已由任务摘要补充说明 | 7角色评审报告完整性存疑，Arch视角的技术风险分析可能不够深入 | 已记录，待后续补充Arch专项评审 | 架构师 [F-50新增] |

### 3.2 技术债务提醒

| 债务项 | 说明 | 建议 |
|--------|------|------|
| PoC使用SQLite，Phase 1 需迁移至PostgreSQL | 数据库设计已包含双平台DDL | 提前准备Alembic迁移脚本 |
| PoC无Redis缓存，Phase 1 需引入 | 缓存策略已在Deployment Guide中定义 | 缓存层接口先行抽象 |
| 单用户模式，无RBAC | 安全设计已明确排除多租户 | 保持简单，避免过度设计 |

### 3.3 外部依赖风险

| 依赖项 | 风险等级 | 应对措施 |
|--------|----------|----------|
| IAMHERE 数字名片数据接口 | 中 | PoC阶段不启用，Phase1再评估；当前使用OCR+LLM自建链路 |
| CarryMem AI记忆服务 | 低 | 通过Adapter解耦，可降级为本地规则引擎 |
| LLM API (OpenAI/Anthropic) | 中 | 已设计重试降级策略和成本控制机制 |

---

## 📊 四、版本策略声明

### 版本号语义

| 版本范围 | 阶段名称 | 说明 | 当前状态 |
|----------|---------|------|----------|
| **0.1.x** | 初始化阶段 | 项目启动、初步调研、原型验证 | ✅ 已完成 |
| **0.2.x** | **POC阶段** | 核心功能验证、技术可行性证明 | ✅ 已完成 |
| **0.3.x** | **Phase 1 (当前)** | MVP开发、前端集成、托管PoC部署 | 🔄 进行中 |
| **0.4.x** | Phase 2 | 商机匹配恢复、高级功能、多用户支持 | ⬜ 待开始 |

### 文档更新触发条件

以下情况必须更新本文档：
1. 任一设计文档版本号变更
2. 新增或删除功能编号(F-xx)
3. 核心枚举值变更(todo_type/scope/action_type等)
4. 跨文档引用关系调整
5. 进入新阶段(0.2.x → 0.3.x)

---

## ✅ 五、Sprint 0 冻结前检查清单

在进入编码阶段前，请逐项确认以下内容：

### 必须完成 (Must)

- [ ] **M1**: 所有13份文档版本号已在上表中记录且实际文件头部一致
- [ ] **M2**: PRD的50项功能编号(F-01~F-50)在技术设计和API设计中均可追溯 [F-50新增]
- [ ] **M3**: 数据库设计的核心表(events/entities/associations/todos/voice_sessions)与API设计的CRUD端点一一对应 [F-50新增]
- [ ] **M4**: 安全设计的PII规则已在API设计的响应脱敏中体现
- [ ] **M5**: 测试计划包含12项P0功能的测试用例（至少每个P0功能1个正向用例，含F-50）[F-50新增]
- [ ] **M6**: Deployment_Guide中的Docker命令可在本地成功执行(`docker-compose -f docker-compose.poc.yml up`)
- [ ] **M7**: LLM_Prompt_Templates中的模板可在LLM客户端中成功调用（mock即可）

### 建议完成 (Should)

- [ ] **S1**: Algorithm_Design中的伪代码可通过单元测试（使用pytest）
- [ ] **S2**: Integration_Design中的时序图与实际代码调用链路一致
- [ ] **S3**: UI_UX_Design的关键页面线框图已与产品负责人对齐

### 可以延后 (Could)

- [ ] **C1**: Monitoring_Runbook（运维手册）可在Phase 1前补充
- [ ] **C2**: Contributing.md（贡献指南）可在有外部协作者时补充
- [ ] **C3**: UI_UX_Design完整版（含组件库规范）可待前端框架确定后补充

---

## 📝 六、签署确认

| 角色 | 姓名 | 日期 | 确认项 |
|------|------|------|--------|
| 架构师 | _____________ | ______ | 设计文档技术一致性 |
| 产品负责人 | _____________ | ______ | PRD与实现方案对齐 |
| QA负责人 | _____________ | ______ | 测试计划覆盖完整性 |
| DevOps | _____________ | ______ | 部署配置可执行性 |

---

## 📎 附录：快速参考链接

| 文档 | 快速跳转 |
|------|----------|
| PRD v5.2 | [查看](./spec/PRD_v1.md) |
| 技术设计 v3.2 | [查看](./architecture/PromiseLink_技术设计_v1.md) |
| 数据库设计 v3.0 | [查看](./design/Database_Design_v1.md) |
| API设计 v3.1 | [查看](./design/API_Design_v1.md) |
| 安全设计 v3.1 | [查看](./design/Security_Design_v1.md) |
| 算法设计 v2.8 | [查看](./design/Algorithm_Design_v1.md) |
| 测试计划 v5.1 | [查看](./design/Test_Plan_v1.md) |
| LLM Prompt模板 0.4.1 | [查看](./design/LLM_Prompt_Templates.md) |
| 集成设计 v2.9 | [查看](./design/Integration_Design_v1.md) |
| 部署指南 v0.5.0 | [查看](./design/Deployment_Guide.md) |
| UI/UX设计 v3.1 | [查看](./design/UI_UX_Design_v1.md) |
| 项目状态总览 | [查看](./PROJECT_STATUS.md) |

---

> **维护说明**: 本文档是PromiseLink进入Sprint 0编码前的最终文档质量门禁。每次文档更新后应重新运行此检查清单。
>
> **最后审核**: 2026-06-14 (文档版本同步至PRD v5.2/技术设计 v3.2/API设计 v3.1)
