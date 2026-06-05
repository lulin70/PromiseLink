# EventLink 文档一致性检查清单

> **更新时间**: 2026-06-04
> **阶段**: POC阶段 (0.2.x) — Sprint 0 编码前最终确认
> **目的**: 确认所有设计文档从旧版本全面更新至 0.2.0(POC阶段)，验证跨文档引用一致性

---

## 📋 一、文档版本一致性表

| # | 文档 | 路径 | 当前版本 | 更新日期 | 状态 |
|---|------|------|----------|----------|------|
| 1 | **PRD** | `spec/PRD_v1.md` | **v4.3** | 2026-06-04 | ✅ 生效 |
| 2 | **技术设计** | `architecture/EventLink_技术设计_v1.md` | **v2.5** | 2026-06-04 | ✅ 生效 |
| 3 | **数据库设计** | `design/Database_Design_v1.md` | **0.2.0 (POC)** | 2026-06-04 | ✅ 生效 |
| 4 | **API设计** | `design/API_Design_v1.md` | **0.2.0 (POC)** | 2026-06-04 | ✅ 生效 |
| 5 | **安全设计** | `design/Security_Design_v1.md` | **0.2.0 (POC)** | 2026-06-04 | ✅ 生效 |
| 6 | **算法设计** | `design/Algorithm_Design_v1.md` | **0.2.0 (POC)** | 2026-06-04 | ✅ 生效 |
| 7 | **测试计划** | `design/Test_Plan_v1.md` | **0.2.0 (POC)** | 2026-06-04 | ✅ 生效 |
| 8 | **LLM Prompt模板** | `design/LLM_Prompt_Templates.md` | **0.2.0 (POC)** | 2026-06-04 | ✅ 生效 |
| 9 | **集成设计** | `design/Integration_Design_v1.md` | **0.2.0 (POC)** | 2026-06-04 | ✅ 生效 |
| 10 | **部署指南** | `design/Deployment_Guide.md` | **0.2.0 (POC)** | 2026-06-04 | ✅ 生效 |
| 11 | **UI/UX设计** | `design/UI_UX_Design_v1.md` | **0.2.0 (POC)** [简化版] | 2026-06-04 | ⚠️ 待完善 |
| 12 | **规格说明README** | `spec/README.md` | **v4.3** | 2026-06-04 | ✅ 同步 |
| 13 | **项目状态** | `PROJECT_STATUS.md` | **已同步** | 2026-06-04 | ✅ 最新 |

### 版本对照总结

- **需求层 (P1)**: PRD v4.3 ←→ 技术设计 v2.5（双主文档对齐）
- **设计层 (P3-P7)**: 全部 8 份设计文档统一至 **0.2.0 (POC)**
- **特殊标记**: UI_UX_Design 为简化版，完整版待前端团队确定后补充

---

## 🔍 二、交叉引用一致性检查项

### 2.1 功能编号一致性

| 检查项 | 涉及文档 | 预期结果 | 状态 |
|--------|----------|----------|------|
| PRD功能编号 F-01~F-49 完整性 | PRD §4 | 49项功能全覆盖 | ⬜ 待确认 |
| 技术设计引用的功能编号与PRD一致 | 技术设计 §3~§7 | F-01~F-49 无遗漏/无多余 | ⬜ 待确认 |
| API设计的端点覆盖P0功能 | API Design §3~§7 | F-01/F-02/F-03/F-04/F-06/F-44~F-48 有对应API | ⬜ 待确认 |
| 测试计划的用例覆盖所有P0功能 | Test Plan §3 | 11项P0功能均有测试用例 | ⬜ 待确认 |

**关键编号清单（P0核心）**:
```
F-01 事件语义路由    F-02 管线化实体抽取   F-03 实体归一(5步)
F-04 关联发现(8种)   F-05 商机匹配度(暂停) F-06 Todo生成追踪
F-44 Input Scope分类  F-45 Action Type识别  F-46 RelationshipBrief
F-47 RelationshipStage  F-48 实体属性增强
```

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
| 环境变量模板与代码config.py一致 | `.env.poc.example` ↔ `src/eventlink/config.py` | 必需环境变量全覆盖 | ⬜ 待确认 |

---

## ⚠️ 三、已知遗留问题

### 3.1 文档完整性缺口

| 问题 | 影响 | 计划解决时间 | 负责人 |
|------|------|-------------|--------|
| **UI_UX_Design为简化版**，缺少详细交互流程图和组件规范 | 前端开发可能需要补充设计细节 | Phase 1 前由前端团队确定 | 前端负责人 |
| **F-05商机匹配功能暂停**（PoC阶段不做），但PRD和技术设计中仍有相关描述 | 开发时需注意跳过此功能实现 | Phase 2 恢复 | 产品+架构师 |
| **自建小程序为备选方案**（优先使用IAMHERE），集成设计中微信相关章节为占位 | 如需自建小程序需补充详细设计 | 视业务需求确定 | 移动端开发 |

### 3.2 技术债务提醒

| 债务项 | 说明 | 建议 |
|--------|------|------|
| PoC使用SQLite，Phase 1 需迁移至PostgreSQL | 数据库设计已包含双平台DDL | 提前准备Alembic迁移脚本 |
| PoC无Redis缓存，Phase 1 需引入 | 缓存策略已在Deployment Guide中定义 | 缓存层接口先行抽象 |
| 单用户模式，无RBAC | 安全设计已明确排除多租户 | 保持简单，避免过度设计 |

### 3.3 外部依赖风险

| 依赖项 | 风险等级 | 应对措施 |
|--------|----------|----------|
| IAMHERE 数字名片数据接口 | 中 | 已定义JSON schema，但未联调；备选方案为手动录入 |
| CarryMem AI记忆服务 | 低 | 通过Adapter解耦，可降级为本地规则引擎 |
| LLM API (OpenAI/Anthropic) | 中 | 已设计重试降级策略和成本控制机制 |

---

## 📊 四、版本策略声明

### 版本号语义

| 版本范围 | 阶段名称 | 说明 | 当前状态 |
|----------|---------|------|----------|
| **0.1.x** | 初始化阶段 | 项目启动、初步调研、原型验证 | ✅ 已完成 |
| **0.2.x** | **POC阶段 (当前)** | 核心功能验证、技术可行性证明 | 🔄 进行中 |
| **0.3.x** | Phase 1 | MVP开发、IAMHERE集成、云端部署 | ⬜ 待开始 |
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
- [ ] **M2**: PRD的49项功能编号(F-01~F-49)在技术设计和API设计中均可追溯
- [ ] **M3**: 数据库设计的核心表(events/entities/associations/todos)与API设计的CRUD端点一一对应
- [ ] **M4**: 安全设计的PII规则已在API设计的响应脱敏中体现
- [ ] **M5**: 测试计划包含11项P0功能的测试用例（至少每个P0功能1个正向用例）
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
| PRD v4.3 | [查看](./spec/PRD_v1.md) |
| 技术设计 v2.5 | [查看](./architecture/EventLink_技术设计_v1.md) |
| 数据库设计 0.2.0 | [查看](./design/Database_Design_v1.md) |
| API设计 0.2.0 | [查看](./design/API_Design_v1.md) |
| 安全设计 0.2.0 | [查看](./design/Security_Design_v1.md) |
| 算法设计 0.2.0 | [查看](./design/Algorithm_Design_v1.md) |
| 测试计划 0.2.0 | [查看](./design/Test_Plan_v1.md) |
| LLM Prompt模板 0.2.0 | [查看](./design/LLM_Prompt_Templates.md) |
| 集成设计 0.2.0 | [查看](./design/Integration_Design_v1.md) |
| 部署指南 0.2.0 | [查看](./design/Deployment_Guide.md) |
| UI/UX设计 0.2.0 | [查看](./design/UI_UX_Design_v1.md) |
| 项目状态总览 | [查看](./PROJECT_STATUS.md) |

---

> **维护说明**: 本文档是EventLink进入Sprint 0编码前的最终文档质量门禁。每次文档更新后应重新运行此检查清单。
>
> **最后审核**: 2026-06-04 (POC阶段文档全面更新完成)
