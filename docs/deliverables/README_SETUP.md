<!-- ⚠️ 本文档已过时，仅供参考。Todo类型名和部分文件名已更新（如card_scan→card_save，todo_type枚举值已变更），请参考最新版PRD v4.0。 -->

# PromiseLink 项目脚手架搭建完成 ✅

## 已完成的工作

### 1. 项目配置文件
- ✅ `pyproject.toml` - 项目配置和依赖管理
- ✅ `requirements.txt` - 生产依赖
- ✅ `requirements-dev.txt` - 开发依赖
- ✅ `.env.example` - 环境变量模板

### 2. 数据库层
- ✅ `src/promiselink/database.py` - 数据库连接管理（支持SQLite和PostgreSQL）
- ✅ `src/promiselink/models/event.py` - Event模型
- ✅ `src/promiselink/models/entity.py` - Entity模型
- ✅ `src/promiselink/models/association.py` - Association模型
- ✅ `src/promiselink/models/todo.py` - Todo + SnoozeSchedule模型

所有模型完全对齐技术设计文档v1.7 §3.1规范。

### 3. API层
- ✅ `src/promiselink/main.py` - FastAPI应用入口
- ✅ `src/promiselink/config.py` - 配置管理
- ✅ `src/promiselink/api/v1/health.py` - 健康检查接口
- ✅ `src/promiselink/api/v1/events.py` - Event接入API

### 4. Docker配置
- ✅ `Dockerfile` - 应用容器化
- ✅ `docker-compose.yml` - 多服务编排（支持PostgreSQL和Redis）

---

## 快速启动指南

### 方式1：本地开发环境（推荐用于PoC）

```bash
# 1. 进入项目目录
cd PromiseLink

# 2. 创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入LLM API密钥等配置

# 5. 创建数据目录
mkdir -p data

# 6. 启动应用
python -m uvicorn promiselink.main:app --reload

# 访问 API 文档
open http://localhost:8000/docs
```

### 方式2：Docker Compose（一键启动）

```bash
# 使用SQLite（最简单）
docker-compose up --build

# 使用PostgreSQL
docker-compose --profile postgres up --build

# 使用Redis缓存
docker-compose --profile redis up --build

# 全部启动
docker-compose --profile postgres --profile redis up --build
```

---

## 验证安装

### 1. 健康检查
```bash
curl http://localhost:8000/api/v1/health
# 预期输出：{"status":"healthy","timestamp":"...","service":"promiselink"}
```

### 2. 数据库连接测试
```bash
curl http://localhost:8000/api/v1/health/db
# 预期输出：{"status":"healthy",...,"database":"connected"}
```

### 3. 创建测试Event
```bash
curl -X POST http://localhost:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "card_save",
    "source": "iamhere_app",
    "title": "Business card from 张三",
    "raw_text": "{\"name\": \"张三\", \"company\": \"XX科技\"}",
    "metadata": {"scan_quality": "high"}
  }'
```

### 4. 查看所有Events
```bash
curl http://localhost:8000/api/v1/events
```

---

## 项目结构

```
PromiseLink/
├── src/
│   └── promiselink/
│       ├── __init__.py
│       ├── main.py              # FastAPI应用入口 ✅
│       ├── config.py            # 配置管理 ✅
│       ├── database.py          # 数据库连接 ✅
│       ├── models/              # SQLAlchemy模型 ✅
│       │   ├── __init__.py
│       │   ├── event.py         # Event模型 ✅
│       │   ├── entity.py        # Entity模型 ✅
│       │   ├── association.py   # Association模型 ✅
│       │   └── todo.py          # Todo模型 ✅
│       ├── api/                 # API端点
│       │   └── v1/
│       │       ├── __init__.py
│       │       ├── health.py    # 健康检查 ✅
│       │       └── events.py    # Event API ✅
│       ├── services/            # 核心引擎（待实现）
│       │   ├── entity_resolution.py    # P0-1 实体归一
│       │   ├── association_engine.py   # 关联发现
│       │   ├── opportunity_matcher.py  # P0-2 商机匹配
│       │   └── todo_state_machine.py   # P0-3 状态机
│       └── utils/               # 工具函数（待实现）
├── tests/                       # 测试（待实现）
├── data/                        # SQLite数据库存储
├── pyproject.toml              # 项目配置 ✅
├── requirements.txt            # 依赖 ✅
├── Dockerfile                  # Docker镜像 ✅
├── docker-compose.yml          # Docker编排 ✅
└── .env.example               # 环境变量模板 ✅
```

---

## 下一步工作（Week 1-3 PoC计划）

### Week 1: 基础管线验证（Day 1-7）
- [ ] **Day 1-2**: ✅ 脚手架已完成！
- [ ] **Day 3-4**: 实现3个P0算法模块
  - `services/entity_resolution.py` (§4.4算法)
  - `services/opportunity_matcher.py` (§4.5算法)
  - `services/todo_state_machine.py` (§4.6算法)
- [ ] **Day 5-6**: 完善Event接入API
  - 实现事件处理管线
  - 集成实体抽取（LLM调用）
- [ ] **Day 7**: 整合测试

**Week1退出标准**：
- ✅ 名片JSON解析准确率>95%（20张样本）
- ✅ API响应延迟<200ms
- ✅ 重复事件自动去重

### Week 2-3: 详见技术设计文档§9.0

---

## 技术栈

- **框架**: FastAPI 0.109+ (async/await)
- **数据库**: SQLite (PoC) / PostgreSQL 15 (生产)
- **ORM**: SQLAlchemy 2.0+ (async)
- **LLM**: Anthropic Claude / OpenAI
- **算法**: NetworkX (图算法) + RapidFuzz (模糊匹配)
- **部署**: Docker + Docker Compose

---

## 环境变量说明

关键配置项（`.env`文件）：

```bash
# LLM配置（必填）
LLM_PROVIDER=anthropic           # 或 openai
LLM_API_KEY=sk-ant-xxx          # 你的API密钥
LLM_MODEL=claude-sonnet-4-20250514

# 数据库（PoC阶段用SQLite即可）
DATABASE_URL=sqlite:///./data/promiselink.db

# 实体归一阈值
ENTITY_RESOLUTION_AUTO_MERGE_THRESHOLD=0.85
ENTITY_RESOLUTION_HUMAN_REVIEW_THRESHOLD=0.70

# 商机匹配阈值
OPPORTUNITY_MATCH_STRONG_THRESHOLD=0.80
OPPORTUNITY_MATCH_POTENTIAL_THRESHOLD=0.60
```

---

## 常见问题

### Q1: 如何切换到PostgreSQL？
A: 修改 `.env` 中的 `DATABASE_URL`：
```bash
DATABASE_URL=postgresql://user:password@localhost:5432/promiselink
```
然后用 `docker-compose --profile postgres up` 启动。

### Q2: 数据库表如何初始化？
A: FastAPI启动时会自动调用 `init_db()` 创建所有表。

### Q3: 如何添加新的API端点？
A: 在 `src/promiselink/api/v1/` 下创建新文件，然后在 `main.py` 中 `include_router`。

### Q4: P0三项算法在哪里实现？
A: 
- **实体归一**: `services/entity_resolution.py`（参考技术设计§4.4）
- **商机匹配**: `services/opportunity_matcher.py`（参考技术设计§4.5）
- **Todo状态机**: `services/todo_state_machine.py`（参考技术设计§4.6）

技术设计文档中已有完整的Python代码示例（第616-941行），可直接参考。

---

## 联系方式

- **项目负责人**: 林总（CarryMem团队）
- **合作方**: 许总（IAMHERE数字名片）
- **技术文档**: `docs/architecture/PromiseLink_技术设计_v1.md`
- **产品需求**: `docs/spec/PRD_v1.md`

---

**祝开发顺利！🚀**
