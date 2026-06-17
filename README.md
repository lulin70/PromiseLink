# PromiseLink - AI驱动的个人商务关系经营助手

> **Slogan**: 让每一次连接，都更有价值
>
> **项目状态**: PoC 验收通过 | 基础版 ready | 1210+ 测试全通过 | 67% 覆盖率
>
> **定位**: 先成就关系，再促成合作 — 利他切入的个人商务关系经营系统
>
> **License**: AGPL v3 — 商业使用需遵守许可证条款

## 快速启动

```bash
# 1. 安装依赖
pip install -e '.[dev]'

# 2. 配置环境变量
cp .env.basic.example .env
# 编辑 .env 填入 LLM_API_KEY（Moka AI / OpenAI / Anthropic 任选其一）

# 3. 启动应用（本地直接运行，无需Docker）
python -m uvicorn promiselink.main:app --host 0.0.0.0 --port 8000
# 或使用一键启动脚本
bash scripts/start.sh

# 4. 访问
# API 文档：http://localhost:8000/docs
# 前端界面：http://localhost:8000
```

## 项目结构

```
PromiseLink/
├── src/promiselink/              # 应用源码
│   ├── models/                 # 数据模型（9个模型文件，11个模型类）
│   │   ├── entity.py           # 人物实体
│   │   ├── event.py            # 互动事件
│   │   ├── todo.py             # 行动提醒（6类）
│   │   ├── association.py      # 关联发现
│   │   ├── relationship_brief.py  # 关系简报
│   │   └── voice_session.py    # 语音会话
│   ├── api/v1/                 # REST API（26个路由文件）
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
│   │   ├── wechat_forward.py / email_sync.py  # 数据接入
│   ├── services/               # 核心引擎（38个模块）
│   │   ├── event_pipeline.py   # 13步事件处理管线
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
├── tests/                      # 测试（60个文件 / 1210用例）
├── data/                       # SQLite数据存储
├── scripts/                    # 一键安装/启动脚本 + E2E测试
└── frontend/                   # Taro H5 前端
```

## 核心能力

### 事件处理管线（13步）

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
- 手动输入 / 语音输入 / 微信转发 / CSV导入 / **邮件同步**

### Insight Engine（洞察引擎）
- 动态优先级评分（4维：紧急度×0.4 + 重要度×0.6）
- 隐式反馈学习（完成顺序→关系权重）
- 场景匹配（DependencyAnalyzer + ContextMatcher）

## 文档索引

### 核心文档
- [PRD v5.2](docs/spec/PRD_v1.md) - 产品需求文档
- [技术设计 v3.2](docs/architecture/PromiseLink_技术设计_v1.md) - 完整技术方案
- [项目状态](docs/PROJECT_STATUS.md) - 11阶段生命周期跟踪（55%完成）
- [QUICKSTART](QUICKSTART.md) - 快速开始指南（含配置参考和FAQ）
- [Setup指南](docs/deliverables/README_SETUP.md) - 安装说明（指向QUICKSTART）

### 详细设计文档
- [数据库设计 v3.0](docs/design/Database_Design_v1.md)
- [API设计 v3.1](docs/design/API_Design_v1.md)
- [算法设计 v2.8](docs/design/Algorithm_Design_v1.md)
- [安全设计 v3.1](docs/design/Security_Design_v1.md)
- [测试计划 v5.1](docs/design/Test_Plan_v1.md)
- [集成设计 v2.9](docs/design/Integration_Design_v1.md)
- [部署指南 v0.5.0](docs/design/Deployment_Guide.md)

### 评估报告
- [POC准备度评估](docs/external/for_team/PromiseLink_POC准备度评估报告.md)

## 当前进度

### ✅ 已完成（P1-P9）
- [x] PRD v5.2（关系经营核心闭环 + 向量化语义能力）
- [x] 技术设计 v3.2（Insight Engine + DataSourceAdapter + 向量语义）
- [x] P0核心算法全部实现（实体归一/承诺履行/状态机/关联发现/动态评分）
- [x] FastAPI完整实现（26个路由文件 / 72个API端点）
- [x] 38个服务模块（Pipeline/NLG/SemanticSearch/MemoryProvider等）
- [x] 9个模型文件，11个模型类（entity/event/todo/association/relationship_brief/voice_session等）
- [x] DataSourceAdapter抽象层（手动/语音/微信/CSV/邮件）
- [x] CarryMem协议解耦（NullMemoryProvider优雅降级）
- [x] 加密体系（HMAC-SHA256 + 字段级加密 + 行级安全）
- [x] 60个测试文件 / **1210测试用例** / **67%覆盖率**
- [x] CI/CD + Alembic 就绪
- [x] PoC Demo 4/4场景通过
- [x] 一键安装/启动脚本（本地直接运行，无需Docker）
- [x] Taro H5前端打包发布

### 🔴 未启动
- [ ] 专业版: 网关中继开发（SQLite+relay gateway）
- [ ] 定制版: 团队协作功能（PG+Redis+多租户）

## 技术栈

| 层面 | 技术 |
|------|------|
| **框架** | FastAPI 0.109+ (Python 3.11+) |
| **数据库** | SQLite (基础版+专业版长期方案) / PostgreSQL 15 (定制版) |
| **ORM** | SQLAlchemy 2.0+ (async) |
| **LLM** | Moka AI (Claude Sonnet 4.6) / OpenAI (GPT-5.5) / Anthropic |
| **向量** | sqlite-vec (基础版+专业版) / pgvector (定制版) |
| **缓存** | Redis (定制版) |
| **算法** | NetworkX + RapidFuzz + numpy |
| **部署** | 基础版: 本地直接运行（无需Docker） / 专业版: Docker + 网关中继 / 定制版: Docker Compose + K8s |

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
| 测试用例 | **1210 passed, 109 skipped, 0 failed** |
| 代码覆盖率 | **67%** |
| API路由 | **26个路由文件 / 72个API端点** |
| 服务模块 | **38个** |
| 数据模型 | **9个文件，11个模型类** |
| 文档版本 | PRD v5.2 / Tech v3.2 |
| 产品层级 | 基础版(本地免费) / 专业版(网关中继) / 定制版(团队) |
| 总体进度 | **85%** |

## 产品版本

| 版本 | 定位 | 价格 | 部署方式 |
|------|------|------|----------|
| **基础版** | 本地免费，纯文本交互 | 免费 | 本地直接运行（无需Docker） |
| **专业版** | 网关中继，微信小程序随时访问 | ¥29/月（早鸟价） / ¥49/月（常规价） | 本地Docker + 云中继网关 |
| **定制版** | 销售团队协作，多租户 | 按需定制 | 云端Docker Compose + K8s |

> 基础版为纯文本交互，不包含语音功能和图片扫描功能。专业版依赖云端服务凭证。

## 团队

- **负责人**: 林总（CarryMem团队）
- **合作方**: 许总（IAMHERE数字名片）

## License

AGPL-3.0 — 详见 [LICENSE](LICENSE) 文件
