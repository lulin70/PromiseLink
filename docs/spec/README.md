# PromiseLink 需求规格文档

> **目录**: `docs/spec/`  
> **用途**: 存放产品需求文档（PRD）及相关评审报告

---

## 📋 文档清单

### 核心需求文档

| 文件名 | 版本 | 日期 | 状态 | 说明 |
|--------|------|------|------|------|
| **PRD_v1.md** | v5.8 | 2026-06-22 | ✅ 生效中 | 产品需求文档主文档<br/>含 F-67 关系推进卡 + F-68 Promise 兑现追踪 + F-69 智能跟进提醒 + F-71 关系健康度 + F-72 AI 关系经营建议 |
| PRD_v1_review_report.md | - | 2026-06-01 | ✅ 完成 | 7角色评审报告 |

---

## 📊 需求分级

### P0 核心功能（基础版，12项）
1. **F-01** 事件语义路由
2. **F-02** 管线化实体抽取
3. **F-03** 实体归一（5步算法）
4. **F-04** 关联发现（8种关联类型）
5. **F-05** 商机匹配度（六维打分，PoC阶段暂停）
6. **F-06** Todo生成与追踪
7. **F-44** Input Scope 分类（8种scope自动路由）
8. **F-45** Promise 双向分析（my_promise/their_promise/my_followup）
9. **F-46** Todo 降噪（5→3条去重）
10. **F-47** RelationshipBrief 生成（12模块结构化关系画像）
11. **F-48** RelationshipStage 推进分析（AI建议不自动升级）
12. **F-67** 关系推进卡（v5.7 新增）

> **注**: F-50 智能语音助手、F-08 CSV导入、F-59/F-60/F-61 ASR/TTS/OCR 已迁移至 [PromiseLink-Pro](https://github.com/lulin70/PromiseLink-Pro) 私有仓库

### P1 增强功能（基础版）
- **F-07** 反馈闭环
- **F-09** 人脉关系录入与提取
- **F-14** 会议行动项分解（4类）
- **F-15** 行动建议生成
- **F-16** 模糊查找与交叉检索（语义搜索 F-57）
- **F-17** 安全校验与敏感词过滤
- **F-20** 数据管理中心（CRUD）
- **F-21** 数据导出 API
- **F-55** 依赖性全图谱路径分析
- **F-56** 场景匹配 Event 表驱动
- **F-68** Promise 兑现状态追踪
- **F-69** 智能跟进提醒

### P2 扩展功能（6项）
15. **F-08** 竞对数据
16. **F-10** 图谱可视化
17. **F-11** 专业数据服务
18. **F-12** 个性化
19. **F-18** 语音输出
20. **F-19** 设备接入

---

## 🎯 核心场景

### 4条事件管线
1. **card_save**：扫名片 → 轻量级处理（秒级）
2. **meeting**：会议纪要 → 深度处理（分钟级）
3. **call**：电话记录 → 要点提取
4. **manual**：手动补全 → 自由文本

### 4种会议类型
- **A** 内部协同会议
- **B** 对外商务会议
- **C** 项目复盘会议
- **D** 知识提取会议

### Todo类型（6种，与代码 `todo_state_machine.py` 一致）
- 🟢 **promise**（行动型）：承诺兑现追踪
- 🟣 **help**（行动型）：帮助/资源维护
- 🔵 **care**（信息型）：关注/背景信息
- 🟡 **followup**（行动型）：跟进提醒
- ⚪ **cooperation_signal**（信息型）：合作信号/商机线索
- 🔴 **risk**（信息型）：风险预警

**Promise 双向分析（F-45，与代码 `event_pipeline.py` Step05 一致）**:
- `my_promise` 我方承诺 | `their_promise` 对方承诺
- `my_followup` 我方跟进 | `mutual_action` 双方行动
- `system_reminder` 系统提醒 | `unclear` 不明确

**Todo 状态机（5种状态）**:
- `pending`（默认）→ `in_progress` → `done`
- `pending` / `in_progress` → `dismissed`（终态）
- `pending` / `in_progress` → `snoozed`（定时恢复）

### 8种关联类型
1. `alumni` - 校友关系
2. `ex_colleague` - 前同事
3. `same_city` - 同城
4. `competitor` - 竞对关系
5. `tech_overlap` - 技术重叠
6. `deal_link` - 交易关联
7. `risk_link` - 风险关联（P2）
8. `supply_chain` - 供应链关系

---

## ✅ 验收标准摘要

### Week 1 退出标准
- 20张名片解析准确率 > 95%
- API响应延迟 < 200ms
- 重复事件自动去重

### Week 2 退出标准
- Precision@5 > 70%
- Recall@10 > 60%
- F1-Score > 0.65

### Week 3 退出标准
- E2E延迟 < 10s
- 可录屏Demo演示

---

## 📚 相关文档

- 技术设计：`../architecture/PromiseLink_技术设计_v1.md`
- 评审报告：`../reports/PromiseLink_DevSquad_真实AI评审报告.md`
- 项目状态：`../PROJECT_STATUS.md`

---

*最后更新: 2026-07-05 (v0.8.0-rc2 同步: PRD v5.8 + F-67/F-68/F-69/F-71/F-72 + Promise 双向分析 + F-50 迁移 Pro)*
