# 重复客户人工处理设计（PRD + 架构 + 测试计划）

- 日期：2026-08-16
- 状态：M1 后端 + M2 前端已实现（2026-08-16）；测试见 tests/test_entity_merge_service.py（12 单测）+ tests/test_api_entities_merge.py（10 集成测试）
- 关联：`docs/design/` 既有设计文档；commit 975e40c（去重/合并自动路径验证）
- 范围：基础版电脑端（宽屏 Web）

### 实现与设计的差异记录

- §2.1-B "source==target → 422"：实际实现为 400（VALIDATION_ERROR），遵循 main.py `_BUSINESS_ERROR_STATUS` 统一映射；缺失 source_id 字段仍为 FastAPI 422
- §2.2 "复用 EntityResolutionEngine.merge_entity 的合并语义"：实现时改为 target-priority 深合并（自研于 entity_merge_service）。原因：ResolutionEngine 语义为"新值覆盖旧值"（适配 pipeline 新提取数据更可信），与 AC2.3"冲突以保留方为准"相反
- vector_embeddings 迁移：该表位于语义检索独立 SQLite 文件（非主库 metadata），主 session 上无此表时容错跳过（log: entity_merge_embeddings_skipped）

## 0. 背景与现状

录入事件后 AI 提取人脉实体。`EntityResolutionEngine`（src/promiselink/services/entity_resolution.py）已实现自动合并：

| 置信度 | 动作 | 结果 |
|--------|------|------|
| ≥0.85（auto_merge_threshold） | MERGE | 自动并入已有实体（2026-08-16 e2e 验证：exact_match=1.0 合并成功） |
| 0.70~0.85（confirm_threshold） | CONFIRM | 创建 provisional 实体，等待人工确认 |
| <0.70 | CREATE | 创建新 confirmed 实体 |

**缺口**：人工处理链路完全缺失——

- 无 merge/confirm REST API（api/v1/entities.py 仅有 GET/PATCH/DELETE）
- 前端无 provisional"待确认"标识、无合并入口（frontend/src/pages/entities/）
- provisional 实体静默混在人脉列表，用户无感知、无法处理

当前开发库状态：19 个活跃实体、0 个 provisional、0 组同名重复（存量已清理）。

## 1. PRD

### 1.1 用户故事

**US-1 确认待确认人脉**
> 作为用户，当 AI 不确定新提取的人是否已有档案（置信度 0.70~0.85）时，我希望在人脉列表看到"待确认"标识，并能一键确认或查看详情，以便保持人脉库准确。

验收标准：
- AC1.1 列表中 provisional 实体显示"待确认"徽标（莫兰迪黄褐系，如 #C4B89C 底 + 深棕字），区别于 confirmed
- AC1.2 提供筛选入口：全部 / 待确认
- AC1.3 点击"确认"后徽标消失，实体转为 confirmed（API 同步）
- AC1.4 确认操作幂等：重复点击无副作用

**US-2 人工合并重复客户**
> 作为用户，当我发现两个人脉档案其实是同一人（如"王总/王志强"），我希望在详情页发起合并、选择保留哪个档案，以便合并历史与待办不丢失。

验收标准：
- AC2.1 实体详情页提供"合并重复"入口，弹窗内搜索并选择另一实体
- AC2.2 合并方向可选：把当前档案并入对方 / 把对方并入当前
- AC2.3 合并后：保留档案继承双方属性（非空字段合并、冲突以保留方为准）、别名追加、关联与待办引用全部迁移
- AC2.4 被并档案置为 merged 状态，从列表消失；其详情页跳转到保留档案
- AC2.5 合并操作幂等：对已 merged 实体再次合并返回 409 冲突并提示保留方
- AC2.6 合并记录审计轨迹（merged_at、merged_from、操作来源 user）

**US-3 疑似重复检测**
> 作为用户，我希望系统主动告诉我哪些人脉可能是重复的（同名、同公司/电话），并提供一键处理入口，以便人脉库长期保持干净。

验收标准：
- AC3.1 `GET /api/v1/entities/duplicates` 返回疑似重复组（同 user 同名活跃实体为一组；≥2 个即成组）
- AC3.2 人脉列表顶部：存在疑似重复组时显示横幅"发现 N 组疑似重复人脉"，点击展开组内成员
- AC3.3 组内可直接发起合并（复用 US-2 弹窗）
- AC3.4 检测为即时查询，不引入后台任务

### 1.2 非目标（本期不做）

- 跨 user 合并（单机单用户场景无需求）
- 自动定期扫描（当前 0 组重复，按需触发足够）
- 合并撤销（undo）——merged 实体数据仍在库中，可人工恢复，本期不做 UI

## 2. 架构设计

### 2.1 API 契约

统一前缀 `/api/v1`，认证同现有（Bearer token，user_id 隔离）。

#### A. 确认实体

```
POST /entities/{entity_id}/confirm
```

- 前置：entity 存在、属当前 user、status=provisional
- 行为：status → confirmed
- 响应 200：EntityResponse（status=confirmed）
- 错误：404 NOT_FOUND / 409（status 非 provisional）

#### B. 合并实体（entity-to-entity）

```
POST /entities/{target_id}/merge
Body: { "source_id": "<uuid>" }
```

- 语义：source 并入 target，target 为保留档案
- 事务内执行（单事务，失败全回滚）：
  1. 属性合并：复用 `EntityResolutionEngine.merge_entity` 的合并语义（别名追加、properties 深合并、merge_history 审计、event_ids 追加），source 的 properties 作为 new_entity_data 输入
  2. 引用迁移：
     - `todos.related_entity_id = source.id → target.id`
     - `associations.source_entity_id / target_entity_id = source.id → target.id`；迁移后若与既有行构成 (user, source, target, type) 唯一冲突则合并行（strength 取大者，保留 target 方向）
     - `vector_embeddings.target_id = source.id → target.id`（同 target_type=entity），若 target 已有 embedding 则删除 source 的
  3. source 置 `status='merged'`，`properties.merged_into = target.id`
- 幂等性：source.status 已为 merged 时返回 409，body 含 `merged_into`（前端据此跳转保留档案）
- 禁止：source_id == target_id → 422；source/target 任一为 merged/deleted → 409
- 响应 200：`{ "target": EntityResponse, "migrated": {"todos": n1, "associations": n2, "embeddings": n3} }`

#### C. 疑似重复检测

```
GET /entities/duplicates
```

- 查询：同 (user_id, name) 的活跃实体（status NOT IN merged/deleted）分组，组内成员数 ≥2
- 响应 200：
```json
{ "groups": [
    { "name": "王总",
      "entities": [ {"id": "...", "company": "创新科技", "title": "CEO", "status": "confirmed"}, ... ],
      "hint": "同名" }
] }
```
- hint 字段预留扩展（后续可加"同公司不同名"等规则）

### 2.2 后端实现要点

- 新增文件 `src/promiselink/services/entity_merge_service.py`：entity-to-entity 合并与引用迁移，独立于 ResolutionEngine（其 merge_entity 只接受"新数据 dict"，不处理已有实体间的引用迁移）
- API 路由追加至 `src/promiselink/api/v1/entities.py`
- 全部走 `commit_with_retry`；合并前 `SELECT ... FOR UPDATE` 等价物（SQLite 串行写，事务即可）
- 日志：`entity_manual_merged`（target_id/source_id/migrated counts/user_id）

### 2.3 前端交互（宽屏两栏）

- 列表页 `frontend/src/pages/entities/index.tsx`：
  - provisional 徽标 + 筛选 chip（全部/待确认）
  - 顶部疑似重复横幅（莫兰迪灰粉底 #D9C8C0，深棕文字，非刺眼样式），展开显示组与"合并"按钮
- 详情页 `frontend/src/pages/entities/detail.tsx`：
  - "合并重复"按钮（次级按钮位）→ 弹窗：搜索实体（复用现有实体搜索接口）→ 显示双方关键信息对比（姓名/公司/职位/待办数）→ 选择保留方向 → 确认（二次确认弹层，提示不可逆）
  - 访问已 merged 实体详情时：显示"已并入 X 档案"并提供跳转
- 确认操作：列表行内"确认"chip 按钮，乐观更新 + 失败回滚

### 2.4 安全与合规

- 所有端点校验 user_id 归属（防越权合并他人实体——本地单用户场景仍保留校验习惯）
- 合并不可逆：UI 二次确认；后端保留 merged 墓碑与审计字段，数据可追溯
- 无新增敏感信息暴露；properties 合并沿用现有 PII 加密路径（encrypt_pii_in_properties）

## 3. 测试计划

### 3.1 单元测试（pytest，新增 tests/test_entity_merge_service.py）

| 用例 | 断言 |
|------|------|
| merge 迁移 todos/associations 引用 | 迁移后无任何行引用 source.id |
| 属性深合并与别名追加 | 非空字段继承、merge_history 追加 1 条 |
| 幂等：source 已 merged | 抛 ConflictError，details 含 merged_into |
| source==target | ValidationError |
| 跨 user 合并 | 404 |
| association 唯一约束冲突合并 | 行数不增、strength 取大 |
| confirm 非 provisional | ConflictError |

### 3.2 集成测试（API 层，tests/test_api_entities_merge.py）

- 三端点契约：正常流、404/409/422 全错误码
- 事务回滚：迁移中途构造异常（如 associations 违反约束）→ 全部回滚

### 3.3 E2E（模拟真实用户操作）

1. 录入含模糊人名事件 → 列表出现"待确认"徽标 → 点击确认 → 徽标消失
2. 手工制造两个同名实体 → 横幅出现 → 发起合并 → 被并方从列表消失，其待办在保留方详情可见
3. 访问被被并实体详情 → 提示已并入并可跳转

**E2E 执行结果（2026-08-16，临时 SQLite + 真实 HTTP 全链路，19/19 PASS）**：

- US-3 检测：同名组正确返回（含 company/title 对比信息），merged 实体排除
- US-1 确认：provisional 筛选→确认→筛选清空→重复确认 409
- US-2 合并：待办迁移计数=1、target-priority 属性保留、同名合并不追加冗余别名、被并方列表消失、status=merged + merged_into 指向保留方、迁移待办在保留方 history 可见
- 错误契约：409（含 merged_into）/400（自合并）/404（跨用户或不存在）全符合
- 合并后同名组消失（重复清理闭环）

### 3.4 回归

- 现有 entity/association/todo 相关测试全量通过
- 2026-08-16 自动合并路径（exact_match）不回归

## 4. 里程碑

1. M1 后端：entity_merge_service + 3 API + 单测/集成测试
2. M2 前端：徽标/筛选、合并弹窗、疑似重复横幅
3. M3 E2E + 文档更新（用户手册补"人脉合并"章节）
