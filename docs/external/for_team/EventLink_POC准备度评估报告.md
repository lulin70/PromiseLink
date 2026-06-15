<!-- ⚠️ 本文档已过时，仅供参考。引用的PRD版本(v3.6)和技术设计版本(v1.7)均已更新，当前最新版本请参考PRD v4.0和技术设计v2.2。 -->

# PromiseLink POC准备度评估报告

> **评估时间**: 2026-06-02 20:24  
> **评估人**: Kiro AI  
> **评估范围**: PoC开工准备情况  
> **参考依据**: WorkBuddy AI反馈 + 技术设计文档v1.7 + PRD v3.6

---

## 一、WorkBuddy AI的诊断

WorkBuddy提到的两个阻塞问题：

1. **技术设计P0三项补齐**
   - 归一算法
   - 商机匹配
   - Todo状态机

2. **FastAPI项目脚手架搭建**

---

## 二、实际情况核查

### 2.1 技术设计P0三项 —— ✅ 已全部补齐

根据技术设计文档v1.7的变更记录，**P0三项已在v1.5版本中全部补齐**：

#### ✅ P0-1: 实体归一5步算法（§4.4）

**完成情况**: **100% 完成**

- ✅ 5步级联算法完整实现（精确匹配→别名匹配→模糊匹配→上下文匹配→人工确认）
- ✅ 置信度分级处理（≥0.85自动合并，[0.70,0.85)人工确认，<0.70创建新实体）
- ✅ `EntityResolutionEngine` 完整代码实现（含rapidfuzz模糊匹配）
- ✅ `ResolutionResult` 数据结构定义
- ✅ 城市别名归一化函数（含北京/上海/深圳/广州/杭州）
- ✅ 撤回机制设计

**代码示例**: 第616-718行，包含完整的Python实现代码

#### ✅ P0-2: 商机匹配度算法（§4.5）

**完成情况**: **100% 完成**（v1.6升级为六维）

- ✅ 六维打分法实现：
  - keyword_overlap (25%)
  - industry_alignment (20%)
  - topic_similarity (15%)
  - llm_semantic (10%)
  - history_collaboration (10%)
  - **callability 可调用度 (20%)** ← 根据李总反馈新增
- ✅ `OpportunityMatcher` 完整代码实现
- ✅ 资源敏感度2级过滤（matchable/no_match）
- ✅ 匹配推理可解释（`_generate_reason`函数）
- ✅ 关系强度影响匹配度逻辑

**代码示例**: 第724-857行，包含完整的Python实现代码

**架构升级**: v1.6根据"私密助手"定位校准，将"你的需求匹配你人脉的供给"作为核心逻辑，可调用度成为最关键维度（权重20%）

#### ✅ P0-3: Todo状态机（§4.6）

**完成情况**: **100% 完成**

- ✅ 5状态定义（pending/in_progress/done/dismissed/snoozed）
- ✅ 状态转移规则 `VALID_TRANSITIONS` 定义
- ✅ `TodoStateMachine` 完整代码实现
- ✅ Snooze定时恢复机制（`recover_expired_snoozes`）
- ✅ 数据库表设计（`snooze_schedules`表）
- ✅ SQL DDL补充（CHECK约束+索引）

**代码示例**: 第860-941行，包含完整的Python实现代码

**数据库支持**:
```sql
ALTER TABLE todos ADD CONSTRAINT todo_status_check
    CHECK (status IN ('pending', 'in_progress', 'done', 'dismissed', 'snoozed'));

CREATE TABLE snooze_schedules (
    todo_id UUID PRIMARY KEY REFERENCES todos(id) ON DELETE CASCADE,
    original_status VARCHAR(15) NOT NULL,
    recover_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

### 2.2 FastAPI项目脚手架 —— ❌ 未搭建

**实际情况**: **0% 完成**

根据 `PROJECT_STATUS.md` P8阶段检查：

```
P8: 实施阶段 (Implementation)
| 检查项 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 开发环境搭建 | ❌ 未开始 | - | FastAPI项目脚手架 |
| Event接入API | ❌ 未开始 | - | POST /api/v1/events |
| 实体抽取模块 | ❌ 未开始 | - | LLM NER pipeline |
...
```

**缺失内容**:
- ❌ 无 `src/` 目录
- ❌ 无 `pyproject.toml` / `requirements.txt`
- ❌ 无 FastAPI 应用入口 `main.py`
- ❌ 无 Docker 配置文件
- ❌ 无数据库迁移脚本
- ❌ 无测试框架配置

---

## 三、POC开工准备度评估

### 3.1 总体评估: 🟡 **技术就绪，工程未就绪**

| 维度 | 状态 | 完成度 | 说明 |
|------|------|--------|------|
| **需求定义** | ✅ | 100% | PRD v3.6已完成，152处量化指标 |
| **架构设计** | ✅ | 95% | 技术设计v1.7完整，等许总确认 |
| **核心算法** | ✅ | 100% | P0三项全部补齐，代码级伪代码完整 |
| **数据模型** | ✅ | 100% | 4表设计+JSONB扩展+索引优化 |
| **API设计** | ✅ | 100% | 含请求/响应示例，可直接开发 |
| **安全设计** | ✅ | 90% | JWT+加密+审计+GDPR完整 |
| **项目脚手架** | ❌ | 0% | **零代码实现** |
| **依赖配置** | ❌ | 0% | 无requirements.txt |
| **数据库初始化** | ❌ | 0% | 无迁移脚本 |
| **Docker配置** | ✅ | 50% | 文档有docker-compose示例，未落地 |

**结论**: **技术设计100%就绪，但无一行工程代码**

---

### 3.2 WorkBuddy的判断是否准确？

#### WorkBuddy说：技术设计P0三项未补齐

**Kiro评估**: ❌ **不准确** 

- 实际情况：P0三项**已在v1.5版本全部补齐**（2026-06-02更新）
- WorkBuddy可能看的是旧版本，或未注意到变更记录第2135-2136行
- 三项算法均有完整的Python代码实现，不是伪代码

#### WorkBuddy说：FastAPI项目脚手架未搭建

**Kiro评估**: ✅ **完全准确**

- PromiseLink目录下确实无任何Python代码
- 无项目结构、无依赖配置、无Docker实例
- 仅有丰富的文档（MD/HTML），但文档≠代码

---

## 四、POC开工的真实阻塞点

### 阻塞点1: 许总未确认技术方案 🔴 **商务阻塞**

根据 `PROJECT_STATUS.md`:
```
P2 Gate 判定: 🟡 有条件通过 — 架构设计完整，等待许总对技术方案的反馈。
进入P3的条件: 许总确认技术方案 → 即可进入详细设计
```

**影响**: 虽然技术设计已完成，但合作方未书面确认，存在方向调整风险

### 阻塞点2: 项目脚手架零实现 🔴 **工程阻塞**

**缺失的关键路径**:
1. FastAPI应用框架搭建（1天）
2. SQLAlchemy ORM模型实现（1天）
3. Docker开发环境配置（0.5天）
4. Alembic数据库迁移（0.5天）
5. pytest测试框架配置（0.5天）

**总计**: 约3.5天基础工程工作

### 阻塞点3: 外部依赖未准备 🟡 **数据阻塞**

根据 `PROJECT_STATUS.md` 下一步行动：
```
5 | 向许总索取IAMHERE名片JSON样例 | 林总 | 20张脱敏名片数据 | P8 前置 |
6 | 配置Moka AI API连接 | CarryMem | 实体抽取pipeline可运行 | P8 前置 |
```

**影响**: 
- 无样例数据 → 无法测试名片解析管线
- 无LLM API → 无法验证实体抽取准确率

---

## 五、POC开工建议

### 5.1 立即可做（不依赖外部）

#### 优先级P0: 搭建项目脚手架（预计3天）

```bash
# 建议的项目结构
PromiseLink/
├── src/
│   ├── promiselink/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI应用入口
│   │   ├── config.py                  # 配置管理
│   │   ├── models/                    # SQLAlchemy模型
│   │   │   ├── event.py
│   │   │   ├── entity.py
│   │   │   ├── association.py
│   │   │   └── todo.py
│   │   ├── api/                       # API端点
│   │   │   ├── v1/
│   │   │   │   ├── events.py
│   │   │   │   ├── entities.py
│   │   │   │   ├── associations.py
│   │   │   │   └── todos.py
│   │   ├── services/                  # 核心引擎
│   │   │   ├── entity_resolution.py  # §4.4算法实现
│   │   │   ├── association_engine.py # §4.3算法实现
│   │   │   ├── opportunity_matcher.py# §4.5算法实现
│   │   │   ├── todo_state_machine.py # §4.6算法实现
│   │   │   └── llm_strategy.py       # §4.2 LLM调用
│   │   ├── adapters/                  # 外部适配器
│   │   │   ├── memory_provider.py    # CarryMem Protocol
│   │   │   └── null_memory.py        # 降级实现
│   │   └── utils/
│   │       ├── city_normalizer.py    # 城市别名归一
│   │       └── validators.py         # 数据校验
├── tests/
│   ├── test_entity_resolution.py
│   ├── test_opportunity_matcher.py
│   └── test_todo_state_machine.py
├── alembic/                           # 数据库迁移
│   ├── versions/
│   └── env.py
├── docker-compose.poc.yml             # PoC部署配置
├── Dockerfile
├── pyproject.toml                     # 依赖管理
├── requirements.txt
└── README.md
```

#### 优先级P1: 实现核心算法模块（预计2天）

基于技术设计文档中的伪代码，将以下3个P0算法转为可运行代码：

1. **EntityResolutionEngine** (§4.4, 第616-718行)
   - 输入: `new_entity: dict, user_id: str`
   - 输出: `ResolutionResult`
   - 依赖: `rapidfuzz`, `SQLAlchemy`

2. **OpportunityMatcher** (§4.5, 第724-857行)
   - 输入: `todo: Todo, person: Entity`
   - 输出: `dict` (总分+六维分数+推理)
   - 依赖: `numpy`, LLM SDK

3. **TodoStateMachine** (§4.6, 第860-941行)
   - 输入: `todo: Todo, new_status: str`
   - 输出: 更新后的 `Todo`
   - 依赖: `SQLAlchemy`, `asyncio`

#### 优先级P2: 数据库初始化（预计1天）

1. 根据§3.1的SQL DDL创建Alembic迁移脚本
2. 配置SQLite开发环境（PoC阶段）
3. 实现4张核心表的ORM模型

---

### 5.2 等待外部输入后执行

#### 等待1: 许总确认技术方案

**触发后**:
- 进入P8实施阶段
- 锁定需求范围
- 开始编码冲刺

#### 等待2: 获取样例数据

**需要的数据**:
```json
// 20张IAMHERE名片JSON样例（脱敏）
{
  "name": "张三",
  "company": "XX科技有限公司",
  "title": "供应链总监",
  "phone": "138****1234",
  "wechat": "zhangsan_wx",
  "email": "zhangsan@example.com",
  "address": "深圳市南山区",
  "industry": "工业互联网"
}
```

**用途**:
- 测试名片JSON解析准确率目标：>95%（PRD §3.1 F-01验收标准）
- 验证实体归一引擎的去重能力

#### 等待3: 配置Moka AI/Claude API

**需要的配置**:
```bash
# .env文件
LLM_PROVIDER=moka_ai  # 或 anthropic
LLM_API_KEY=sk-...
LLM_MODEL=claude-sonnet-4-20250514
LLM_MAX_TOKENS=2000
LLM_TEMPERATURE=0.3
```

**用途**:
- 实体抽取准确率验证（目标≥90%，PRD §3.1 F-02）
- 关联发现F1验证（目标>0.65，PRD §3.1 F-04）

---

## 六、3周PoC冲刺计划（修正版）

根据技术设计§9.0，PoC目标是验证6项核心假设：

### Week 1: 基础管线验证（Day 1-7）

| Day | 任务 | 产出 | 验收标准 |
|-----|------|------|---------|
| 1-2 | 搭建FastAPI脚手架+数据库 | 可运行的API框架 | `GET /health` 返回200 |
| 3-4 | 实现3个P0算法模块 | 单元测试通过 | 覆盖率≥80% |
| 5-6 | 实现Event接入API | POST /api/v1/events可用 | 接收JSON返回event_id |
| 7 | 整合测试+缓冲 | Week1 Demo可演示 | 名片→Event→Entity |

**Week1退出标准**（PRD §3.0.1）:
- ✅ 名片JSON解析准确率>95%（20张样本）
- ✅ API响应延迟<200ms
- ✅ 重复事件自动去重

### Week 2: 核心引擎验证（Day 8-14）

| Day | 任务 | 产出 | 验收标准 |
|-----|------|------|---------|
| 8-9 | 实现关联发现引擎 | AssociationEngine可用 | 8种关联类型可生成 |
| 10-11 | 实现Todo生成引擎 | TodoGenerator可用 | 6种Todo类型可生成 |
| 12-13 | 商机匹配度测试 | 匹配度计算准确 | 与人工标注对比 |
| 14 | Week2整合测试 | E2E流程打通 | Event→Todo完整流程 |

**Week2退出标准**（PRD §3.0.1）:
- ✅ 关联发现Precision@5>70%
- ✅ 关联发现Recall@10>60%
- ✅ F1>0.65
- ✅ 商机匹配度计算延迟<1s

### Week 3: 资源识别+演示准备（Day 15-21）

| Day | 任务 | 产出 | 验收标准 |
|-----|------|------|---------|
| 15-16 | 资源识别功能 | Person.resource字段提取 | 资源线索确认率≥60% |
| 17-18 | Todo反馈闭环 | 状态更新+统计 | API响应<200ms |
| 19 | 性能优化 | E2E延迟优化 | 名片→Todo<5s |
| 20 | 准备Demo场景 | 3个典型场景可演示 | 商机/风险/背景各1个 |
| 21 | 录屏+文档 | PoC交付包 | 视频+指标报告 |

**Week3退出标准**（PRD §3.0.1）:
- ✅ E2E延迟：名片→Todo<5秒，会议→Todo<60秒
- ✅ 资源线索确认率≥60%
- ✅ 可录屏Demo演示
- ✅ 许总团队确认"方向正确"

---

## 七、风险提示

### 风险1: 时间预估偏乐观 ⚠️

**原因**: 
- 技术设计虽完整，但算法伪代码→生产代码有调试成本
- LLM API延迟不可控（Claude Sonnet平均3-5s，文档§8.0.2）
- 实体归一的人工确认界面需要开发

**建议**: 
- Week1-2聚焦算法验证，界面用Swagger UI临时替代
- 准备spaCy降级方案（文档§4.2），LLM不稳定时切换

### 风险2: 数据依赖不可控 🔴

**如果许总无法提供样例数据**:
- 用开源名片数据集（如GitHub上的VCard样例）
- 自行构造20张合成名片JSON
- **但这会降低PoC说服力**（真实数据vs模拟数据）

### 风险3: 算法准确率未达标 ⚠️

**应对**:
- 实体归一：阈值可调（当前0.85/0.70），可降低到0.80/0.65
- 关联发现：F1目标0.65已是宽松标准（文档§3.0.1）
- 商机匹配：六维算法权重可动态调整（文档§4.5）

---

## 八、总结与建议

### WorkBuddy的诊断：部分准确

| WorkBuddy的说法 | 实际情况 | 准确度 |
|----------------|---------|--------|
| 技术设计P0三项未补齐 | ❌ 已补齐（v1.5版本） | 不准确 |
| FastAPI项目脚手架未搭建 | ✅ 确实未搭建 | 完全准确 |

### Kiro的评估：技术就绪，工程未动工

**已就绪**:
- ✅ PRD v3.6: 152处量化指标，7角色审核通过
- ✅ 技术设计v1.7: 2137行完整设计，含代码级伪代码
- ✅ P0算法: 归一/匹配/状态机均有完整实现代码
- ✅ API设计: 含请求/响应示例，可直接开发
- ✅ 数据模型: 4表+JSONB+索引+触发器完整

**未就绪**:
- ❌ 项目脚手架: 零代码
- ❌ 依赖配置: 无requirements.txt
- ❌ 数据库脚本: 无迁移脚本
- ❌ Docker配置: 无实例文件
- ❌ 样例数据: 无IAMHERE名片JSON

### 给林总的建议

#### 🎯 立即行动（本周内，不依赖外部）

1. **搭建FastAPI脚手架**（2天）
   - 初始化项目结构
   - 配置pyproject.toml + Docker
   - 实现SQLAlchemy ORM模型

2. **实现3个P0算法模块**（1.5天）
   - EntityResolutionEngine
   - OpportunityMatcher  
   - TodoStateMachine
   - 编写单元测试（覆盖率≥80%）

3. **联系许总**（持续跟进）
   - 催促技术方案反馈
   - 索取20张脱敏名片JSON样例
   - 确认LLM API配置细节

#### 📋 许总确认后（Week 1-3冲刺）

按照上文§六的3周PoC计划执行

#### ⚠️ 风险管控

- 准备Plan B: 如果许总数据不到位，用开源数据集替代
- 降级策略: 如果LLM不稳定，切换spaCy规则引擎
- 进度透明: 每周五向许总同步进度+演示半成品

---

## 九、最终判断

### PromiseLink的POC是否准备好开工？

**Kiro的判断**: 🟡 **50%准备好**

```
技术设计层面: ✅ 100%就绪
工程实施层面: ❌   0%就绪
外部依赖层面: 🟡  50%就绪（等许总反馈+数据）
```

**推荐路径**: 

```
立即开工 → 搭建脚手架（3天）→ 同时催许总 → 拿到数据后进入Week2验证
              ↓
         不要再等了！
    技术设计已经过度完善（2137行）
       是时候写代码了
```

**一句话总结**: 

> PromiseLink不缺设计，缺的是第一行代码。WorkBuddy对"P0三项未补齐"的判断不准确，但对"脚手架未搭建"的诊断完全正确。建议立即搭建FastAPI项目框架（3天），然后等许总数据到位后进入3周PoC冲刺。

---

*评估完成 | Kiro AI | 2026-06-02*
