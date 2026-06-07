# EventLink - AI驱动的个人商务关系经营助手

> **项目状态**: PoC 验收通过 | Phase 1 开发中 | 654 测试全通过 | 72% 覆盖率
>
> **定位**: 先成就关系，再促成合作 — 利他切入的个人商务关系经营系统

## 快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 MOKA_AI_API_KEY (Moka AI) 或 OPENAI_API_KEY

# 3. 启动应用
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
python -m uvicorn eventlink.main:app --reload --port 8000

# 4. 访问API文档
open http://localhost:8000/docs
```

## 项目结构

```
EventLink/
├── src/eventlink/              # 应用源码
│   ├── models/                 # 数据模型（6张表）
│   │   ├── entity.py           # 人物实体
│   │   ├── event.py            # 互动事件
│   │   ├── todo.py             # 行动提醒（6类）
│   │   ├── association.py      # 关联发现
│   │   ├── relationship_brief.py  # 关系简报
│   │   └── voice_session.py    # 语音会话
│   ├── api/v1/                 # REST API（17个端点）
│   │   ├── health.py           # 健康检查
│   │   ├── events.py           # 事件CRUD + Pipeline触发
│   │   ├── entities.py         # 实体管理
│   │   ├── todos.py            # Todo管理
│   │   ├── associations.py     # 关联查询
│   │   ├── relationship_briefs.py  # 关系简报
│   │   ├── dashboard.py        # 数据看板
│   │   ├── voice.py / voice_query.py  # 语音输入/查询
│   │   ├── import_csv.py       # CSV导入
│   │   ├── export.py           # 数据导出
│   │   ├── demand_input.py     # 需求输入
│   │   ├── auth.py             # 认证
│   │   └── wechat_forward.py / email_sync.py  # 数据接入（Phase 1）
│   ├── services/               # 核心引擎（28个模块）
│   │   ├── event_pipeline.py   # 14步事件处理管线
│   │   ├── entity_extractor.py    # LLM实体提取
│   │   ├── entity_resolution.py    # 实体归一（5步算法）
│   │   ├── todo_generator.py       # Todo生成（6类型策略）
│   │   ├── todo_state_machine.py   # Todo状态机
│   │   ├── promise_fulfillment.py  # 承诺履行追踪
│   │   ├── association_discovery.py # 关联发现（3策略）
│   │   ├── priority_scorer.py      # 动态优先级评分
│   │   ├── nlg_service.py          # 自然语言生成
│   │   ├── llm_client.py           # LLM客户端（Moka AI）
│   │   ├── semantic_search.py      # 向量语义搜索
│   │   ├── memory_provider.py      # CarryMem集成
│   │   └── ...                     # （20+ 其他服务模块）
│   ├── core/                    # 基础设施
│   │   ├── crypto.py           # 加密（HMAC-SHA256+字段加密）
│   │   ├── exceptions.py       # 三层异常体系
│   │   ├── natural_date.py     # 自然日期解析
│   │   └── logging.py / redis.py / wechat.py
│   ├── prompts/                # LLM Prompt模板
│   └── main.py                 # FastAPI入口
├── docs/                       # 文档体系
├── tests/                      # 测试（41个文件 / 654用例）
├── data/                       # SQLite数据存储
└── docker-compose.yml          # Docker配置
```

## 核心能力

### 事件处理管线（14步）

```
原始输入 → 输入分类 → 实体提取 → 实体归一 → Todo生成(6类)
→ 关联发现(3策略) → 动态评分 → 状态更新 → NLG响应生成
```

**Todo 类型**（雾色系）:
| 类型 | 颜色 | 含义 |
|------|------|------|
| promise | 雾绿 | 承诺事项 |
| help | 雾紫 | 帮助建议 |
| care | 雾蓝 | 关注提醒 |
| followup | 雾金 | 后续跟进 |
| cooperation_signal | 雾白 | 合作信号 |
| risk | 烟粉 | 风险预警 |

### 数据接入层（DataSourceAdapter）
- 手动输入 / 语音输入 / 微信转发 / CSV导入 / **邮件同步（Phase 1）**

### Insight Engine（洞察引擎）
- 动态优先级评分（4维：紧急度×0.4 + 重要度×0.6）
- 隐式反馈学习（完成顺序→关系权重）
- 场景匹配（DependencyAnalyzer + ContextMatcher）

## 文档索引

### 核心文档
- [PRD v4.7](docs/spec/PRD_v1.md) - 产品需求文档（向量化语义能力）
- [技术设计 v2.8](docs/architecture/EventLink_技术设计_v1.md) - 完整技术方案
- [项目状态](docs/PROJECT_STATUS.md) - 11阶段生命周期跟踪（75%完成）
- [Setup指南](docs/deliverables/README_SETUP.md) - 详细安装和启动说明

### 详细设计文档（v2.x 全部就绪）
- [数据库设计 v2.7](docs/design/Database_Design_v1.md)
- [API设计 v2.7](docs/design/API_Design_v1.md)
- [算法设计 v2.7](docs/design/Algorithm_Design_v1.md)
- [安全设计 v2.7](docs/design/Security_Design_v1.md)
- [测试计划 v2.7](docs/design/Test_Plan_v1.md)
- [集成设计 v2.7](docs/design/Integration_Design_v1.md)
- [部署指南 0.4.0](docs/design/Deployment_Guide.md)

### 评估报告
- [POC准备度评估](docs/reports/EventLink_POC准备度评估报告.md)

## 当前进度

### ✅ 已完成（P1-P9）
- [x] PRD v4.7（关系经营核心闭环 + 向量化语义能力）
- [x] 技术设计 v2.8（Insight Engine + DataSourceAdapter + 向量语义）
- [x] P0核心算法全部实现（实体归一/承诺履行/状态机/关联发现/动态评分）
- [x] FastAPI完整实现（17个API端点）
- [x] 28个服务模块（Pipeline/NLG/SemanticSearch/MemoryProvider等）
- [x] 6个数据模型（entity/event/todo/association/relationship_brief/voice_session）
- [x] DataSourceAdapter抽象层（手动/语音/微信/CSV/邮件）
- [x] CarryMem协议解耦（NullMemoryProvider优雅降级）
- [x] 加密体系（HMAC-SHA256 + 字段级加密 + 行级安全）
- [x] 41个测试文件 / **654测试用例** / **72%覆盖率**
- [x] Docker + CI/CD + Alembic 就绪
- [x] PoC Demo 4/4场景通过

### ⏳ Phase 1 进行中
- [ ] 邮件集成完整流程
- [ ] 长按反馈交互机制
- [ ] 4D优先级模型完善
- [ ] 推送通知（微信模板消息/移动推送/小程序卡片）

### 🔴 未启动
- [ ] Phase 2: 日历集成 + 上下文感知推送
- [ ] 小程序前端开发
- [ ] 生产环境K8s部署

## 技术栈

| 层面 | 技术 |
|------|------|
| **框架** | FastAPI 0.109+ (Python 3.11+) |
| **数据库** | SQLite (PoC) / PostgreSQL 15 (Phase 1) |
| **ORM** | SQLAlchemy 2.0+ (async) |
| **LLM** | Moka AI (Claude Sonnet 4) / OpenAI兼容 |
| **向量** | sqlite-vec (PoC) / pgvector (生产) |
| **缓存** | Redis (Phase 1) |
| **算法** | NetworkX + RapidFuzz + numpy |
| **部署** | Docker + Docker Compose |

## 验证安装

```bash
# 健康检查
curl http://localhost:8000/api/v1/health

# 创建互动事件（触发完整Pipeline）
curl -X POST http://localhost:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "meeting",
    "source": "manual",
    "raw_text": "今天和张总聊了合作，他说下周需要一份技术方案"
  }'

# 查询实体列表
curl http://localhost:8000/api/v1/entities

# 查询Todo列表（含动态优先级排序）
curl http://localhost:8000/api/v1/todos

# 语义搜索
curl "http://localhost:8000/api/v1/entities/search?q=技术合作"
```

## 质量指标

| 指标 | 数值 |
|------|------|
| 测试用例 | **654 passed, 0 failed** |
| 代码覆盖率 | **72%** (5884 stmts / 1626 missed) |
| API端点 | **17个** |
| 服务模块 | **28个** |
| 数据模型 | **6个** |
| 文档版本 | PRD v4.7 / Tech v2.8 |

## 团队

- **负责人**: 林总（CarryMem团队）
- **合作方**: 许总（IAMHERE数字名片）

## License

MIT
