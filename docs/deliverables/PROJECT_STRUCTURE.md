<!-- ⚠️ 本文档已过时，仅供参考。Todo类型名和部分文件名已更新（如card_scan→card_save，todo_type枚举值已变更），请参考最新版PRD v4.0。 -->

# EventLink 项目结构说明

> **版本**: v0.1.0  
> **更新时间**: 2026-06-02  
> **状态**: FastAPI脚手架已搭建完成

---

## 目录结构（按DevSquad规范整理）

```
EventLink/
├── README.md                      # 项目概览
├── .gitignore                     # Git忽略规则
├── .env.example                   # 环境变量模板
├── pyproject.toml                 # Python项目配置
├── requirements.txt               # 生产依赖
├── requirements-dev.txt           # 开发依赖
├── Dockerfile                     # Docker镜像构建
├── docker-compose.yml             # Docker编排配置
│
├── src/                           # 📦 源代码
│   └── eventlink/                 # 主应用包
│       ├── __init__.py
│       ├── main.py                # FastAPI应用入口
│       ├── config.py              # 配置管理
│       ├── database.py            # 数据库连接
│       │
│       ├── models/                # 数据模型（SQLAlchemy）
│       │   ├── __init__.py
│       │   ├── event.py           # Event模型
│       │   ├── entity.py          # Entity模型
│       │   ├── association.py     # Association模型
│       │   └── todo.py            # Todo + SnoozeSchedule模型
│       │
│       ├── api/                   # API端点
│       │   └── v1/
│       │       ├── __init__.py
│       │       ├── health.py      # 健康检查
│       │       └── events.py      # Event CRUD
│       │
│       ├── services/              # 核心业务逻辑（待实现）
│       │   ├── entity_resolution.py    # P0-1: 实体归一
│       │   ├── association_engine.py   # 关联发现
│       │   ├── opportunity_matcher.py  # P0-2: 商机匹配
│       │   └── todo_state_machine.py   # P0-3: Todo状态机
│       │
│       └── utils/                 # 工具函数（待实现）
│           ├── city_normalizer.py
│           └── validators.py
│
├── tests/                         # 🧪 测试（待实现）
│   ├── test_entity_resolution.py
│   ├── test_opportunity_matcher.py
│   └── test_todo_state_machine.py
│
├── scripts/                       # 🔧 脚本工具
│   ├── run_review.py              # DevSquad评审脚本
│   ├── run_review_real_ai.py      # 真实AI评审
│   └── run_*.py                   # 其他评审脚本
│
├── docs/                          # 📚 文档
│   ├── PROJECT_STATUS.md          # 项目生命周期状态
│   │
│   ├── spec/                      # 需求规格
│   │   ├── PRD_v1.md              # 产品需求文档v1
│   │   └── PRD_v1_review_report.md
│   │
│   ├── architecture/              # 架构设计
│   │   └── EventLink_技术设计_v1.md  # 技术设计文档v1.7
│   │
│   ├── planning/                  # 项目计划
│   │   ├── 20260601_会议纪要.md
│   │   ├── 20260602_许总团队讨论纪要.md
│   │   └── 会议待确认事项清单.md
│   │
│   ├── reports/                   # 📊 评审报告（已整理）
│   │   ├── EventLink_POC准备度评估报告.md
│   │   ├── EventLink_DevSquad_真实AI评审报告.md
│   │   ├── EventLink_产品设计评审报告.md
│   │   ├── EventLink_产品设计讨论报告.md
│   │   ├── EventLink_技术方案V3_技术版.md
│   │   ├── EventLink_技术方案V3_网页版.html
│   │   └── ...（其他报告）
│   │
│   ├── deliverables/              # 📤 交付物
│   │   ├── PROJECT_STRUCTURE.md   # 本文档
│   │   └── README_SETUP.md        # 快速启动指南
│   │
│   ├── internal/                  # 🔒 内部文档
│   │   ├── EventLink_产品架构V2_数字名片整合方案.md
│   │   ├── EventLink_PRD+技术设计_联合审阅报告_CarryMem.md
│   │   └── ...（AI评审报告、会议纪要等）
│   │
│   └── external/                  # 📋 对外文档
│       ├── for_team/              # 团队共享
│       │   ├── EventLink_最终总结报告.md
│       │   ├── EventLink_分工模型V2.1_修正版.md
│       │   └── EventLink_一页纸方案_V2_精简版.md
│       │
│       ├── for_许总/               # 许总（IAMHERE）
│       │   └── EventLink_技术方案V3_网页版.html
│       │
│       └── for_李总/               # 李总（反馈）
│           └── EventLink_产品核心价值升级建议_资源匹配供给与维护版.md
│
├── data/                          # 💾 数据存储
│   └── eventlink.db               # SQLite数据库（PoC）
│
└── archive/                       # 📦 归档
    └── drafts/                    # 早期草稿
        └── EventLink_一页纸方案_给许总.md
```

---

## 核心模块说明

### 1. 数据模型（`src/eventlink/models/`）

所有模型100%对齐技术设计文档v1.7 §3.1规范：

#### Event模型
- 4种事件类型：`card_save`, `meeting`, `call`, `manual`
- 最大raw_text: 500KB
- 索引：user_id + event_type + timestamp

#### Entity模型
- 5种实体类型：`person`, `organization`, `topic`, `technology`, `project`
- 支持实体归一：canonical_name + aliases
- properties字段：JSONB/JSON存储实体属性

#### Association模型
- 8种关联类型：`alumni`, `ex_colleague`, `same_city`, `competitor`, `tech_overlap`, `deal_link`, `risk_link`, `supply_chain`
- strength分数：0-1浮点数，支持时间衰减
- 外键级联删除

#### Todo模型
- 6种Todo类型：`opportunity`, `risk`, `context`, `action`, `resource`, `maintenance`
- 5种状态：`pending`, `in_progress`, `done`, `dismissed`, `snoozed`
- SnoozeSchedule子表：支持Todo暂停/恢复

### 2. API端点（`src/eventlink/api/v1/`）

#### Health API
- `GET /api/v1/health` - 基础健康检查
- `GET /api/v1/health/db` - 数据库连接检查

#### Event API
- `POST /api/v1/events` - 创建事件
- `GET /api/v1/events` - 列表查询（支持过滤）
- `GET /api/v1/events/{id}` - 获取详情
- `DELETE /api/v1/events/{id}` - 删除事件

### 3. 待实现模块（Week 1 Day 3-4）

#### P0三项核心算法

**P0-1: 实体归一引擎** (`services/entity_resolution.py`)
- 5步级联算法：精确→别名→模糊→上下文→人工确认
- 置信度阈值：0.85（自动合并），0.70（人工审核）
- 参考：技术设计§4.4，第616-718行

**P0-2: 商机匹配器** (`services/opportunity_matcher.py`)
- 六维打分法：keyword(25%) + industry(20%) + topic(15%) + llm(10%) + history(10%) + callability(20%)
- 匹配度阈值：0.80（强匹配），0.60（潜在匹配）
- 参考：技术设计§4.5，第724-857行

**P0-3: Todo状态机** (`services/todo_state_machine.py`)
- 5状态转移规则：pending ⇄ in_progress ⇄ done
- Snooze机制：定时恢复到原状态
- 参考：技术设计§4.6，第860-941行

---

## 如何运行

### 方式1：本地开发

```bash
cd EventLink

# 设置PYTHONPATH（重要！）
export PYTHONPATH=./src

# 安装依赖
pip install -r requirements.txt

# 配置环境
cp .env.example .env

# 启动应用
python -m uvicorn eventlink.main:app --reload

# 访问文档
open http://localhost:8000/docs
```

### 方式2：Docker

```bash
cd EventLink

# 构建并启动
docker-compose up --build

# 访问
curl http://localhost:8000/api/v1/health
```

---

## 文档分类说明

### 📊 reports/ - 评审和分析报告
存放所有DevSquad生成的评审报告、分析报告、讨论报告等。

### 📤 deliverables/ - 交付物
存放给用户的交付文档，如快速启动指南、项目结构说明等。

### 🔒 internal/ - 内部文档
存放团队内部的讨论记录、AI评审报告、决策记录等。

### 📋 external/ - 对外文档
- `for_team/` - 团队共享的文档
- `for_许总/` - 给许总（IAMHERE）的技术方案
- `for_李总/` - 给李总的产品建议

### 📝 spec/ - 需求规格
产品需求文档（PRD）和相关评审报告。

### 🏗️ architecture/ - 架构设计
技术设计文档、架构决策记录（ADR）等。

### 📅 planning/ - 项目计划
会议纪要、待办事项、时间线等。

---

## 当前状态

### ✅ 已完成
- [x] 项目脚手架搭建
- [x] 数据库模型（4张表完整实现）
- [x] FastAPI应用框架
- [x] 基础API（Health + Events）
- [x] Docker配置
- [x] 文档整理（按DevSquad规范）

### ⏳ 进行中
- [ ] P0三项核心算法实现（Week1 Day3-4）

### 📋 待办
- [ ] 事件处理管线
- [ ] LLM集成
- [ ] 单元测试（覆盖率≥80%）
- [ ] 性能优化

---

## 联系方式

- **项目负责人**: 林总（CarryMem团队）
- **合作方**: 许总（IAMHERE数字名片）
- **技术文档**: `docs/architecture/EventLink_技术设计_v1.md`
- **产品需求**: `docs/spec/PRD_v1.md`
- **项目状态**: `docs/PROJECT_STATUS.md`

---

*文档生成时间: 2026-06-02 20:49*
