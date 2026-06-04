# EventLink 文档完整性清单

> **更新时间**: 2026-06-03 (第五轮更新：P0缺口补齐——结构化日志+错误处理+Prompt模板库+小程序边界缺口标记)
> **审核者**: 7角色共识审核  
> **目的**: 对照标准软件工程文档体系，识别EventLink项目所有文档缺漏与过时内容

---

## 📋 文档体系总览

### ✅ 已完成且最新的文档

#### 1. 需求与规划类
- ✅ **PRD_v1.md** (spec/) — 内容版本v4.0
  - 定位：AI驱动的个人商务关系经营助手——先成就关系，再促成合作
  - 核心闭环：互动→关注→承诺→帮助→反馈
  - Todo类型：promise/help/care/followup/cooperation_signal/risk
  
- ✅ **EventLink_技术设计_v1.md** (architecture/) — 内容版本v2.2
  - Todo类型DDL更新、AI输出语言规则、匹配算法阶段化
  - §8.0.6 数据库迁移策略（Alembic）、§8.0.7 结构化日志规范（structlog）、§8.0.8 统一错误处理与降级策略
  
- ✅ **会议纪要** (planning/)
  - 20260601_会议纪要.md
  - 20260602_许总团队讨论纪要.md
  - 分类体系方向_会议备忘.md
  - 会议待确认事项清单.md

#### 2. 详细设计类
- ✅ **Database_Design_v1.md** (design/) — v1.2 ✅ 已更新（Todo类型重命名、concern/promise/contribution字段）
- ✅ **API_Design_v1.md** (design/) — v1.3 ✅ 已更新（Todo类型重命名、concern/promise API、AI输出语言规则、§8 API版本管理策略全面补齐）
- ✅ **Algorithm_Design_v1.md** (design/) — v1.2 ✅ 已更新（Todo类型重命名、匹配算法阶段化、AI输出语言规则算法）
- ✅ **Integration_Design_v1.md** (design/) — v1.2 ✅ 已更新（Todo类型重命名、12个Prompt模板、AI输出语言规则）
- ✅ **UI_UX_Design_v1.md** (design/) — v1.2 ✅ 已更新（首次体验4屏、首页重构、Todo类型视觉更新）
- ✅ **Test_Plan_v1.md** (design/) — v1.2 ✅ 已更新（Todo类型重命名、产品指标、AI输出语言规则测试、E2E场景更新）
- ✅ **Security_Design_v1.md** (design/) — v1.1 ✅ 已更新（AI输出安全约束、concern/promise数据安全）
- ✅ **Deployment_Guide.md** (design/) — v1.0 ✅ 新建（684行，8章节完整部署指南）
- ✅ **LLM_Prompt_Templates.md** (design/) — v1.0 ✅ 新建（12个Prompt模板独立文档，含AI输出语言规则+模型选择策略+重试降级+成本控制）

#### 3. 7角色共识报告
- ✅ **PRD_v3.2_7角色审核报告.md** (internal/)
- ✅ **技术设计_v1.2_7角色审核报告.md** (internal/)
- ✅ **WorkBuddy审阅_7角色共识.md** (internal/)
- ✅ **李总资源匹配建议_7角色共识.md** (internal/)
- ✅ **定位校准_7角色共识.md** (internal/)

#### 4. 外部交付物
- ✅ **for_李总/** — 李总反馈原始文档+图片
- ✅ **for_许总/** — 技术方案网页版
- ✅ **for_team/** — 一页纸方案+分工模型+总结报告

#### 5. 项目管理
- ✅ **PROJECT_STATUS.md** (docs/)
- ✅ **README_SETUP.md** (deliverables/)
- ✅ **PROJECT_STRUCTURE.md** (deliverables/)

---

## ✅ 已更新的文档（2026-06-03 第二轮）

| 文档 | 原版本 | 新版本 | 变更内容 | 行数变化 |
|------|--------|--------|----------|---------|
| Database_Design_v1.md | v1.0 | v1.1 | 移除RLS、Todo类型6种、敏感度字段、数据主权 | ~600→~700 |
| API_Design_v1.md | v1.0 | v1.1 | Todo类型6种、RBAC移除、Resources API新增 | ~930→~1100 |
| Algorithm_Design_v1.md | v1.0 | v1.1 | 从索引扩展为完整文档、6种Todo、敏感度、callability | ~90→1574 |
| Integration_Design_v1.md | v1.0 | v1.1 | ticket模式、10个Prompt模板、CarryMem集成 | ~230→2564 |
| UI_UX_Design_v1.md | v1.0 | v1.1 | 莫兰迪色系、移除分享按钮、6种Todo视觉规范 | ~130→1114 |
| Test_Plan_v1.md | v1.0 | v1.1 | event_type修正、6种Todo测试、安全测试、E2E场景 | ~466→1575 |

## ✅ 已创建的缺失文档（2026-06-03）

| 文档 | 版本 | 行数 | 核心内容 |
|------|------|------|---------|
| Security_Design_v1.md | v1.0 | 1393 | JWT认证、临时授权码、PII加密、LLM安全、数据主权 |
| docker-compose.poc.yml | - | ~60 | PoC部署配置（健康检查、资源限制、日志配置） |
| .env.poc.example | - | ~40 | PoC环境变量模板 |

---

## ⚠️ 仍需更新的文档（低优先级）

| 文档 | 问题 | 优先级 |
|------|------|--------|
| spec/README.md | 引用不存在的P2评审报告 | P2 |
| architecture/README.md | 引用不存在的评审报告 | P2 |

---

## ❌ 仍缺失的文档

### 🔴 ~~P0 - 阻塞PoC开发~~ ✅ 已完成
- ✅ **Security_Design_v1.md** — 安全设计文档（v1.0, 1393行）
  - 包含：JWT认证、单用户数据隔离（无RBAC）、PII加密、LLM输入消毒、临时授权码

- ✅ **docker-compose.poc.yml** — PoC部署配置（已创建）
  - 包含：健康检查、资源限制、日志配置、.env.poc.example

### 🟡 P1 - Phase 1前必须补齐
- ❌ **Deployment_Guide.md** — 部署指南
  - PoC本地部署 + Phase 1云端部署步骤
  
- ~~❌ **LLM_Prompt_Templates.md** — LLM Prompt模板库~~ ✅ 已创建（v1.0）
  - 事件抽取、实体归一、关联发现、Todo生成、资源识别的Prompt模板

### 🟢 P2 - 持续迭代中补齐
- ❌ **Monitoring_Runbook.md** — 运维手册
- ❌ **Contributing.md** — 贡献指南

---

## 📁 目录结构（清理后）

```
EventLink/
├── docs/
│   ├── spec/                    # 产品规格
│   │   ├── PRD_v1.md           # PRD v4.0
│   │   ├── PRD_v1_review_report.md
│   │   └── README.md
│   ├── architecture/            # 架构设计
│   │   ├── EventLink_技术设计_v1.md  # 技术设计 v1.7
│   │   └── README.md
│   ├── design/                  # 详细设计
│   │   ├── API_Design_v1.md          # v1.1
│   │   ├── Algorithm_Design_v1.md    # v1.1
│   │   ├── Database_Design_v1.md     # v1.1
│   │   ├── Integration_Design_v1.md  # v1.1
│   │   ├── Security_Design_v1.md     # v1.0 (NEW)
│   │   ├── Test_Plan_v1.md           # v1.1
│   │   ├── UI_UX_Design_v1.md        # v1.1
│   │   └── README.md
│   ├── internal/                # 内部审核报告
│   │   ├── PRD_v3.2_7角色审核报告.md
│   │   ├── 技术设计_v1.2_7角色审核报告.md
│   │   ├── WorkBuddy审阅_7角色共识.md
│   │   ├── 李总资源匹配建议_7角色共识.md
│   │   ├── 定位校准_7角色共识.md
│   │   ├── EventLink_P1_客户视角评审报告.md
│   │   ├── EventLink_P2_客户视角架构设计报告.md
│   │   ├── EventLink_P2_架构设计_7角色评审报告.md
│   │   ├── EventLink_PRD+技术设计_联合审阅报告_CarryMem.md
│   │   ├── EventLink_PRD_v1.5_7角色评审报告.md
│   │   ├── EventLink_PRD_v1.7_目标用户视角评审报告.md
│   │   ├── EventLink_李总反馈_PM+架构师.md
│   │   ├── EventLink_李总反馈v2_PM+架构师.md
│   │   ├── EventLink_李总资源匹配建议_审阅分析.md
│   │   ├── EventLink_MVP讨论_PM+架构师.md
│   │   └── EventLink_POC准备度评估报告.md
│   ├── external/                # 外部交付物
│   │   ├── for_李总/            # 李总反馈原始文档+图片
│   │   ├── for_许总/            # 技术方案网页版
│   │   └── for_team/            # 团队交付物
│   ├── planning/                # 会议纪要
│   ├── deliverables/            # 交付物
│   ├── reports/                 # 评估报告（已清理重复）
│   │   ├── EventLink_POC准备度评估报告.md
│   │   ├── EventLink_一页纸方案_给许总.md
│   │   └── EventLink_DevSquad_真实AI评审报告.md
│   ├── DOCUMENTATION_CHECKLIST.md
│   └── PROJECT_STATUS.md
├── scripts/                     # 7角色共识脚本（保留）
│   ├── run_v32_review.py
│   ├── run_v32_review_r2.py
│   ├── run_workbuddy_consensus.py
│   ├── run_lizong_consensus.py
│   └── run_positioning_review.py
├── src/eventlink/               # 应用源码
│   ├── api/v1/
│   ├── models/
│   ├── config.py
│   ├── database.py
│   └── main.py
├── README.md
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── docker-compose.poc.yml      # PoC部署配置 (NEW)
├── .env.poc.example            # PoC环境变量模板 (NEW)
├── requirements.txt
└── requirements-dev.txt
```

---

## 🔑 关键决策备忘（文档更新时必须遵守）

1. **产品定位**：AI驱动的**个人商务关系经营助手**——先成就关系，再促成合作（非"资源匹配平台"）
2. **核心闭环**：互动→关注→承诺→帮助→反馈
3. **Todo类型**：promise/help/care/followup/cooperation_signal/risk（莫兰迪色系）
4. **匹配算法**：六维 — keyword(25%)+industry(20%)+topic(15%)+llm(10%)+history(10%)+callability(20%)；PoC阶段先做承诺兑现闭环
5. **敏感度**：2级 — matchable/no_match
6. **部署**：PoC本地Docker+SQLite → Phase1云端Docker Compose+PG+Redis
7. **明确排除**：RBAC/多租户/团队协作/他人资源匹配/原生APP
8. **字段名**：todo_type（非todo_nature）、callability（非availability）
9. **AI输出语言规则**：推测必须标记、禁止自动判定资源、禁止建议索取资源
10. **首次体验**：从"扫名片"改为"记录一次重要交流"（4屏新流程）
11. **API版本管理**：三层SemVer（主版本URL/次版本响应头/补丁版本内部）+ 12个月废弃过渡期 + Alembic数据库迁移
12. **P2 Gate**：7角色架构评审加权共识82%（≥70%门槛），许总不参与技术决策
13. **结构化日志**：structlog + JSON格式 + request_id传递 + 脱敏规则（手机号/邮箱/姓名）
14. **错误处理**：EventLinkError异常层次（Business/LLM/Infrastructure）+ 降级决策矩阵 + 熔断器
15. **小程序边界缺口**：Phase1前必须补齐——IAMHERE名片JSON格式、微信用户映射表、card_save metadata schema
