# EventLink - AI驱动的个人商务关系经营助手

> **项目状态**: FastAPI脚手架已搭建完成 ✅ | PRD v4.0 | 技术设计 v2.0

## 快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY

# 3. 启动应用
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
python -m uvicorn eventlink.main:app --reload

# 4. 访问API文档
open http://localhost:8000/docs
```

## 项目结构

```
EventLink/
├── src/eventlink/          # 应用源码 ✅
│   ├── models/            # 数据库模型（4张表）
│   ├── api/v1/            # API端点（Health + Events）
│   ├── services/          # 核心引擎（待实现）
│   └── main.py           # FastAPI入口
├── docs/                  # 文档
│   ├── spec/             # PRD等规格文档
│   ├── architecture/     # 技术设计文档
│   ├── reports/          # 评审报告（已整理）✅
│   ├── deliverables/     # 交付物（Setup指南等）✅
│   ├── planning/         # 会议纪要
│   ├── internal/         # 内部文档
│   └── external/         # 对外文档
├── scripts/              # 工具脚本（已整理）✅
├── tests/                # 测试（待实现）
├── data/                 # SQLite数据存储
└── docker-compose.yml   # Docker配置 ✅
```

## 文档索引

### 核心文档
- [PRD v4.0](docs/spec/PRD_v1.md) - 产品需求文档（关系经营核心闭环）
- [技术设计 v2.0](docs/architecture/EventLink_技术设计_v1.md) - 完整技术方案
- [项目状态](docs/PROJECT_STATUS.md) - 11阶段生命周期跟踪
- [Setup指南](docs/deliverables/README_SETUP.md) - 详细安装和启动说明

### 详细设计文档
- [数据库设计](docs/design/Database_Design_v1.md) - 数据模型与表结构设计
- [API设计](docs/design/API_Design_v1.md) - RESTful API端点设计
- [算法设计](docs/design/Algorithm_Design_v1.md) - 核心算法（实体归一/承诺履行/状态机）
- [集成设计](docs/design/Integration_Design_v1.md) - 外部系统集成方案
- [UI/UX设计](docs/design/UI_UX_Design_v1.md) - 界面与交互设计
- [安全设计](docs/design/Security_Design_v1.md) - 安全策略与权限控制
- [测试计划](docs/design/Test_Plan_v1.md) - 测试策略与用例设计
- [部署指南](docs/design/Deployment_Guide.md) - 部署与运维方案

### 评估报告
- [POC准备度评估](docs/reports/EventLink_POC准备度评估报告.md) - 2026-06-02最新评估

### 对外交付
- [技术方案网页版](docs/external/for_许总/EventLink_技术方案V3_网页版.html) - 给许总的提案

## 当前进度

### ✅ 已完成（P1-P7）
- [x] PRD v4.0（关系经营核心闭环：互动→关注→承诺→帮助→反馈）
- [x] 技术设计 v2.0（架构+数据+API设计）
- [x] P0三项算法设计（实体归一+承诺履行+状态机）
- [x] FastAPI项目脚手架
- [x] 数据库模型（4张表完整实现）
- [x] 基础API（Health + Events CRUD）
- [x] Docker配置
- [x] 8份详细设计文档（Database/API/Algorithm/Integration/UI_UX/Security/Test_Plan/Deployment）
- [x] docker-compose.poc.yml + .env.poc.example

### ⏳ 进行中（P8）
- [ ] P0三项算法实现（Week1 Day3-4）
- [ ] 事件处理管线
- [ ] LLM集成
- [ ] 单元测试

### 🔴 阻塞项
- 许总未确认技术方案
- 等待20张名片样例数据
- 等待LLM API配置

## 技术栈

- **框架**: FastAPI 0.109+ (Python 3.11+)
- **数据库**: SQLite (PoC) / PostgreSQL 15 (生产)
- **ORM**: SQLAlchemy 2.0+ (async)
- **LLM**: Anthropic Claude / OpenAI
- **算法**: NetworkX + RapidFuzz
- **部署**: Docker + Docker Compose

## 验证安装

```bash
# 健康检查
curl http://localhost:8000/api/v1/health

# 创建测试Event - 名片扫描（身份补充入口）
curl -X POST http://localhost:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "card_scan",
    "source": "test",
    "title": "测试名片",
    "raw_text": "{\"name\": \"张三\"}"
  }'

# 创建测试Event - 会面记录
curl -X POST http://localhost:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "meeting",
    "source": "test",
    "title": "与张三午餐会面",
    "raw_text": "{\"contact\": \"张三\", \"topic\": \"合作意向讨论\", "promise\": \"下周发送方案\"}"
  }'
```

## 下一步工作

**核心闭环**: 互动→关注→承诺→帮助→反馈

**Week 1 (Day 3-4)**: 实现P0三项核心算法
- `src/eventlink/services/entity_resolution.py` - 实体归一5步算法
- `src/eventlink/services/promise_fulfillment.py` - 承诺履行引擎
- `src/eventlink/services/todo_state_machine.py` - Todo状态机

**Todo类型**: promise / help / care / followup / cooperation_signal / risk

参考技术设计文档§4.4-§4.6（第616-941行有完整Python代码）

## 团队

- **负责人**: 林总（CarryMem团队）
- **合作方**: 许总（IAMHERE数字名片）

## License

MIT
