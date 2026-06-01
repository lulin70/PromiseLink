#!/usr/bin/env python3
"""
EventLink P1: PM writes PRD, then all 7 roles review for consensus.
Uses Moka AI (Claude Sonnet) as real LLM backend.
Two-phase dispatch: Phase 1 = PM writes PRD, Phase 2 = All roles review.
"""

import sys
import os
import time

sys.path.insert(0, "../DevSquad")

from scripts.collaboration.dispatcher import MultiAgentDispatcher
from scripts.collaboration.llm_backend import create_backend

PROJECT_DIR = "."
OUTPUT_DIR = os.path.join(PROJECT_DIR, "docs", "spec")

os.makedirs(OUTPUT_DIR, exist_ok=True)

BACKEND_CONFIG = {
    "provider": "openai",
    "api_key": os.environ.get("MOKA_API_KEY", ""),
    "base_url": os.environ.get("MOKA_BASE_URL", "https://api.moka-ai.com/v1"),
    "model": os.environ.get("MOKA_MODEL", "moka/claude-sonnet-4-6"),
}

PRD_CONTEXT = """
你是 EventLink 项目的产品经理。请根据以下完整背景信息，撰写一份正式的 PRD（产品需求文档）。

## 项目背景

EventLink 是 CarryMem 记忆系统的扩展模块，核心定位：
**数字名片 + AI 关联发现引擎 = 自动发现隐藏的商脉和人脉线索**

合作方：许总（IAMHERE 数字名片小程序）
技术方：林总（CarryMem 团队，负责全部后端和算法）

## 三层架构

- 第一层（应用层）：信息入口 — IAMHERE数字名片小程序、AI录音卡/录音笔（恒智易R1等）、视频会议纪要（腾讯会议/飞书）
- 第二层（引擎层）：事件标准化 — 多源数据接收、格式标准化→统一Event Schema、AI实体抽取（人名/公司/技能/项目）、元数据自动丰富
- 第三层（引擎层）：关联发现引擎 — 实体归一Engine → 关联发现Engine → 提醒生成Engine，底层支撑：实体图谱(NetworkX) + 规则引擎

## 分工原则

- 应用层：前端展示和用户运营（面向用户的触点，由合作方负责）
- 引擎层：后端服务和核心算法（AI处理与关联计算，由CarryMem负责）
- 应用层无需部署服务器/无需维护AI模型/无需后端团队
- 对接方式：标准HTTP API（附带SDK和示例代码）

## 核心数据模型

1. Event: id, event_type(card_scan|meeting|call|manual), source, title, timestamp, raw_text, entities, metadata
2. Entity: id, entity_type(person|organization|technology|project|attribute), name, aliases, properties
3. Association: source_entity, target_entity, relation_type, strength(0.0~1.0), evidence
4. Alert: alert_type(opportunity⚪|risk🔴|context🔵), priority, title, detail, suggestion

## 7种关联类型

alumni(校友), ex_colleague(前同事), competitor(竞对), tech_overlap(技术重叠), deal_link(交易链), risk_link(风险链), supply_chain(供应链)

## 3类提醒

- ⚪ 机会型：商机关联发现（技术匹配度≥0.80推送强匹配）
- 🔴 风险型：竞对关系预警
- 🔵 背景型：上下文信息补充（校友/投资偏好等）

## 核心算法

### 实体归一（5步）
1. 精确匹配（confidence=1.0）
2. 别名扩展查找
3. 上下文相似度计算（公司+0.3, 技能+0.2, 共现+0.3）
4. 置信度分级：≥0.85自动合并（记录日志），[0.70,0.85)进入待确认队列，<0.70新建实体。**所有自动合并均支持撤回(Rollback)**
5. 人工确认流程(Human-in-the-Loop)：展示属性对比+AI理由+历史案例，操作：确认合并/拒绝合并/稍后处理。确认结果反哺模型。

### 关联发现（3步）
A. 共现频率分析
B. 类型推断（同公司→ex_colleague, 技能重叠→tech_overlap, 竞品匹配→competitor）
C. 时间衰减+过滤

### 技术匹配度计算（4维打分）
- 技能-需求关键词重叠(Jaccard相似度): +0.35
- 行业领域一致性: +0.25
- LLM语义理解: +0.20
- 历史合作信号: +0.05
- 合计: 0.85(85%)
- 阈值: ≥0.80强匹配, [0.60,0.80)潜在机会, <0.60不推送

## 数据来源（关键决策）

### 竞对关系数据来源
①公开网页信息（企业官网/新闻稿/行业报道）自动检索行业分类与产品关键词
②用户在名片/事件中手动标注的竞争关系
③系统根据"同一行业+相似产品关键词"自动推断并标记为待确认
第一期基于公开网页信息，后续验证效果后可接入专业数据服务增强。
**排除**：公开信息爬取（法律风险）、政府采购数据爬取（口头沟通）
**延后**：第三方付费数据服务（付费版再考虑）

### 校友/投资偏好数据
- 第一期：用户手动补充（名片/联系人档案中填写教育背景、投资方向）
- 后期：第三方付费服务（投资人画像API等）

## 技术栈

FastAPI(Python 3.11+), NetworkX+igraph, Moka AI(Claude Sonnet)/OpenAI, spaCy+自定义词典(降级), PostgreSQL 15, Redis 7, Docker Compose→K8s

## 安全设计

TLS 1.3, JWT(access:15min/refresh:7d), RBAC+行级隔离, AES-256-GCM字段级加密, API Key钥匙串存储, 审计日志, GDPR合规

## API接口

- POST /api/v1/events — 上报事件
- GET /api/v1/alerts/today?limit=10 — 查询今日提醒
- POST /api/v1/alerts/{id}/feedback — 用户反馈(useful/not_useful/dismissed)

## PoC验证计划（3周）

Week1: 数据接入验证 — 20张样例名片解析, 准确率>95%, 延迟<200ms
Week2: 关联发现验证 — Precision@5>70%, Recall@10>60%, F1>0.65, 延迟<2s
Week3: 端到端演示 — 名片录入到提醒展示完整链路, E2E延迟<10s

## 分期路线图

第一期（当前）: 商机匹配+基础竞对预警+手动背景补充 | 名片JSON+录音转文字+公开网页信息检索+用户手工录入
第二期（迭代）: 竞对信号增强+关联准确率优化+提醒个性化 | 专业数据服务接入(验证后决定)+用户反馈闭环训练
第三期（付费增值）: 自动化背景补充+第三方画像接入+行业知识图谱 | 付费数据服务API

## 已确认的设计原则

1. 每一期的核心功能不依赖后期数据源
2. 实体归一必须人工确认，且可撤回
3. 文档使用第三人称客观描述，不用"你/我"指派口吻
4. 第一期完全基于自有数据和用户主动输入即可运行

---

请撰写完整的PRD文档，包含以下章节：
1. 产品概述（愿景、目标用户、核心价值）
2. 用户故事（至少8个，覆盖3类提醒场景）
3. 功能需求清单（P0/P1/P2优先级，含验收标准）
4. 非功能需求（性能、安全、可用性、可扩展性，全部量化）
5. 数据需求（数据来源、数据流、数据治理）
6. 约束与假设
7. 验收标准总表（可量化、可测试）
8. 术语表

输出格式：Markdown，中文撰写。
"""

REVIEW_CONTEXT = """
你是 EventLink 项目的审核成员。请审核刚才PM撰写的PRD文档，从你的专业角色出发：

1. **完整性检查**：是否有遗漏的需求或场景？
2. **一致性检查**：是否与已确认的技术方案和架构设计矛盾？
3. **可测试性检查**：验收标准是否可量化、可测试？
4. **风险识别**：是否有潜在的需求风险或实现风险？
5. **改进建议**：具体的修改建议（标注优先级）

关键审核要点（必须检查）：
- 实体归一是否包含人工确认+撤回机制
- 竞对数据来源是否只包含公开网页信息（不含爬取、不含付费API）
- 分期路线图是否与已确认的三期方案一致
- 验收标准是否全部可量化
- 是否有"你/我"指派口吻（应避免）
- 校友/投资偏好数据第一期是否为手动录入

请给出：通过/有条件通过/不通过，以及具体修改意见。
"""


def run_p1_prd():
    backend = create_backend(
        BACKEND_CONFIG["provider"],
        api_key=BACKEND_CONFIG["api_key"],
        base_url=BACKEND_CONFIG["base_url"],
        model=BACKEND_CONFIG["model"],
    )

    # Phase 1: PM writes PRD
    print("=" * 60)
    print("Phase 1: PM 撰写 PRD 文档")
    print("=" * 60)

    disp = MultiAgentDispatcher(
        llm_backend=backend,
        persist_dir=os.path.join(PROJECT_DIR, "data", "p1_prd"),
    )

    t0 = time.time()
    prd_result = disp.dispatch(
        task_description=PRD_CONTEXT,
        roles=["product-manager"],
        mode="sequential",
    )
    prd_duration = time.time() - t0

    print(f"\nPM PRD generation completed in {prd_duration:.1f}s")
    print(f"Success: {prd_result.success}")

    prd_content = ""
    if prd_result.worker_results:
        for wr in prd_result.worker_results:
            if wr.get("role") == "product-manager":
                prd_content = wr.get("output", "")

    if prd_content:
        prd_path = os.path.join(OUTPUT_DIR, "PRD_v1_draft.md")
        with open(prd_path, "w", encoding="utf-8") as f:
            f.write(prd_content)
        print(f"PRD draft saved to: {prd_path}")
    else:
        print("WARNING: PM produced no output, using summary instead")
        prd_content = prd_result.summary or ""

    disp.shutdown()

    # Phase 2: All 7 roles review the PRD
    print("\n" + "=" * 60)
    print("Phase 2: 全团队 7 角色审核 PRD")
    print("=" * 60)

    review_task = REVIEW_CONTEXT + "\n\n## PRD 文档内容\n\n" + prd_content[:8000]

    disp2 = MultiAgentDispatcher(
        llm_backend=backend,
        persist_dir=os.path.join(PROJECT_DIR, "data", "p1_review"),
    )

    t1 = time.time()
    review_result = disp2.dispatch(
        task_description=review_task,
        roles=["architect", "product-manager", "security", "tester", "solo-coder", "devops", "ui-designer"],
        mode="consensus",
    )
    review_duration = time.time() - t1

    print(f"\n7-role review completed in {review_duration:.1f}s")
    print(f"Success: {review_result.success}")

    review_report = review_result.to_markdown()
    review_path = os.path.join(OUTPUT_DIR, "PRD_v1_review_report.md")
    with open(review_path, "w", encoding="utf-8") as f:
        f.write(review_report)
    print(f"Review report saved to: {review_path}")

    if review_result.consensus_records:
        print(f"\nConsensus records: {len(review_result.consensus_records)}")
        for cr in review_result.consensus_records:
            print(f"  - {cr}")

    disp2.shutdown()

    # Summary
    print("\n" + "=" * 60)
    print("P1 PRD 流程完成")
    print("=" * 60)
    print(f"PRD draft: {prd_path}")
    print(f"Review report: {review_path}")
    print(f"Total time: {prd_duration + review_duration:.1f}s")
    print("\n下一步: 根据审核意见修订PRD → P1 Gate检查")


if __name__ == "__main__":
    run_p1_prd()
