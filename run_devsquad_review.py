#!/usr/bin/env python3
"""
EventLink P1-P7 文档更新清单 - DevSquad 7角色全员Review共识
使用真实Moka AI后端
"""

import os
import sys
import json

# 添加DevSquad到路径
sys.path.insert(0, "../.trae/skills/devsquad")

from scripts.collaboration.dispatcher import MultiAgentDispatcher
from scripts.collaboration.llm_backend import create_backend

# ============================================================
# Moka AI 后端配置
# ============================================================
MOKA_BASE_URL = "https://api.moka-ai.com/v1"
MOKA_MODEL = "moka/claude-sonnet-4-6"
MOKA_API_KEY = "sk-GWSmGaP4XYK3YDWi80gGZTtae8eb7id1mgCAYDdvDgoFpUzX"

# ============================================================
# 任务描述 - 完整的P1-P7文档更新清单Review任务
# ============================================================
TASK_DESCRIPTION = """
## EventLink P1-P7 文档更新完整清单 — 7角色全员Review共识

### 背景
EventLink项目PRD已从v3.6升级到v4.3，技术设计从v1.7升级到v2.5。
docs/design/目录下的9份详细设计文档+3份辅助文档全部基于旧版本，需要全面更新。
已生成97项变更的完整更新清单，现需7角色全员Review达成共识。

### 当前基线
- PRD: v4.3（含F-44~F-49六项新P0功能）
- 技术设计: v2.5（含数据模型/Pipeline/安全加固/CI/CD）

### 12份待更新文档及变更统计

#### 文档1: Database_Design_v1.md (v1.2→v2.0, P0, ~2h)
7项变更(D1-1~D1-7):
- D1-1: relationship_briefs 新表(17字段+3索引+1唯一约束+version) [A类]
- D1-2: events表+2字段(input_scope+input_scope_confidence) [A类]
- D1-3: todos表+6字段(action_type/promisor_id/beneficiary_id/confirmation_status/evidence_quote/evidence_event_id) [A类]
- D1-4: entities.properties JSONB变更(relationship.strength→relationship_stage) [A类]
- D1-5: ER图更新(新增RELATIONSHIP_BRIEFS节点) [A类]
- D1-6: 参考版本号更新
- D1-7: Alembic迁移说明 [D类]

#### 文档2: API_Design_v1.md (v1.2→v2.0, P0, ~3h)
10项变更(D2-1~D2-10):
- D2-1: 新增6个P0 API端点(POST/events加input_scope, GET/relationship-brief, PATCH/stage含乐观锁, GET/dashboard/today, GET/todos?view=my-responses, POST/contributions, POST/feedbacks) [A类]
- D2-2: 日视图API F-49完整定义 [A/B类]
- D2-3: 现有端点变更(PATCH/todos增加action_type等; GET/entities返回relationship_stage) [A类]
- D2-4: 认证章节JWT规范(HS256/黑名单/Refresh旋转/CORS) [C类]
- D2-5: PII脱敏API行为标注 [C类]
- D2-6: input_scope SC-01约束 [C类]
- D2-7: 错误码体系(OPTIMISTIC_LOCK_CONFLICT/INVALID_INPUT_SCOPE) [B/D类]
- D2-8: 数据导出API Phase1提前 [D类]
- D2-9: F-05暂停声明(商机匹配API标记Phase2) [B类]
- D2-10: 参考版本号

#### 文档3: Security_Design_v1.md (v1.2→v2.0, P0, ~2.5h)
10项变更(D3-1~D3-10):
- D3-1: PII检测规则补全(6种PII正则+redact_pii_from_text流程图) [C类]
- D3-2: JWT认证规范(Token格式/Payload/4项安全约束) [C类]
- D3-3: STRIDE威胁模型更新(6类型+场景+缓解措施) [C类]
- D3-4: input_scope SC-01越权防护 [C类]
- D3-5: evidence_quote存储安全(sanitize→存储→不建索引→脱敏) [C类]
- D3-6: Non-goals从4→8项(加商机匹配暂停等) [B类]
- D3-7: TTS安全评估(ASR清洗/TTS不泄露敏感信息) [B/C类]
- D3-8: 数据导出安全(GDPR式导出安全要求) [D类]
- D3-9: 依赖安全评估(httpx/Pydantic/FastAPI基线) [C类]
- D3-10: 参考版本号

#### 文档4: Algorithm_Design_v1.md (v1.2→v2.0, P0, ~3h)
9项变更(D4-1~D4-9):
- D4-1: input_scope分类器算法(InputClassifier.classify规则引擎8种枚举+LLM fallback) [A类]
- D4-2: Promise双向动作识别算法(_extract_promises重写6种action_type) [A类]
- D4-3: Todo降噪算法(单场≤3条截断+Concern/NeedInsight/Contribution不生成Todo) [A类]
- D4-4: RelationshipStage状态机(7阶段枚举+STAGE_TRANSITIONS+RS-01) [A类]
- D4-5: Pipeline Step0/8更新(插入input_scope+追加RelationshipBrief) [A类]
- D4-6: F-05商机匹配暂停标注(feature_flag控制) [B类]
- D4-7: 关键决策铁律更新(action_type 6种补充) [B类]
- D4-8: 关联发现冷热分离(HOT/COLD分类) [A类]
- D4-9: 参考版本号

#### 文档5: Test_Plan_v1.md (v1.2→v2.0, P0, ~2.75h)
9项变更(D5-1~D5-9):
- D5-1: P0功能测试用例(F-44~F-48各≥2正向+1异常) [A类]
- D5-2: F-49日视图测试(同天多会议分组/空日期/非法日期400) [A/B类]
- D5-3: Security专项测试(PII18用例+input_scope越权3用例+JWT3用例+乐观锁2用例) [C类]
- D5-4: 回归测试策略(E2E场景+Sprint阻塞发布) [B/D类]
- D5-5: 测试方法学文档(100条脱敏数据+PM+Arch双签) [D类]
- D5-6: CI/CD集成测试(GitHub Actions步骤细化) [D类]
- D5-7: 监控指标验证(6项P0指标验证方法) [D类]
- D5-8: 退出条件更新(11→14项新增4项) [B类]
- D5-9: 参考版本号

#### 文档6: UI_UX_Design_v1.md (v1.2→v2.0, P1, ~4h)
11项变更(D6-1~D6-11):
- D6-1: 首页改版重大(双核心区域回应驱动型:今天需要我回应+最近值得推进) [B类,60min]
- D6-2: 关系推进卡设计F-47(12模块卡片P0首屏4模块+P1展开3模块+P2详情3模块) [A/B类]
- D6-3: RelationshipStage可视化(7阶段进度条+RS-01用户确认按钮) [A类]
- D6-4: 首次体验流程固定(记录一次重要交流4屏流) [B类]
- D6-5: Slogan更新("让每一次连接，都有回应") [B类]
- D6-6: 日视图F-49(同天多会议独立卡片列表) [A/B类]
- D6-7: Todo视图改造(我的待回应+等待对方回应tab) [A类]
- D6-8: 自建小程序页面Taro备选(MVP 5页线框图) [B/D类]
- D6-9: 人脉推荐移除 [B类]
- D6-10: TTS交互入口位置 [B/D类]
- D6-11: 参考版本号

#### 文档7: Integration_Design_v1.md (v1.2→v2.0, P1, ~2h)
11项变更(D7-1~D7-11):
- D7-1: LLM集成Promise双向Prompt更新(promisor/beneficiary/action_type) [A类]
- D7-2: LLM集成input_scope分类Prompt新增(8种scope+关键词触发+fallback) [A类]
- D7-3: CarryMem集成路径三阶段细化(PoC NullProvider→Phase1基础→Phase2全量) [B/D类]
- D7-4: 微信OAuth不变
- D7-5: TTS/ASR集成方案(ASR Whisper/TTS Azure Edge-TTS/Mock验证端点) [B/D类]
- D7-6: 数字名片API对接预留 [B类]
- D7-7: 通知服务不变
- D7-8: Redis缓存不变
- D7-9: 数据导出集成点 [D类]
- D7-10: 关键决策铁律更新 [B类]
- D7-11: 参考版本号

#### 文档8: Deployment_Guide.md (v1.0→v2.0, P1, ~1.5h)
7项变更(D8-1~D8-7):
- D8-1: Dockerfile多阶段构建(builder→runtime非root+HEALTHCHECK) [D类]
- D8-2: GitHub Actions CI流水线(trigger/strategy/services/steps/lint/test/coverage) [D类]
- D8-3: docker-compose.poc.yml确认一致性 [D类]
- D8-4: 监控指标6项P0 Prometheus定义(histogram/counter+alert阈值) [D类]
- D8-5: 数据库迁移Alembic流程 [D类]
- D8-6: 自建小程序部署Taro备选 [B/D类]
- D8-7: 参考版本号

#### 文档9: LLM_Prompt_Templates.md (v1.2→v2.0, P0, ~2h)
8项变更(D9-1~D9-8):
- D9-1: 新增input_scope分类Prompt(8种scope定义+关键词特征+置信度要求) [A类]
- D9-2: 更新Todo生成Prompt(追加action_type 6种+降噪规则+confirmation_status默认值) [A类]
- D9-3: 更新实体抽取Prompt(追加relationship_stage初始值+properties结构) [A类]
- D9-4: 新增RelationshipBrief生成Prompt(12模块填充prompt聚合生成) [A类]
- D9-5: 新增RelationshipStage推进建议Prompt(AI分析是否可推进但不自动升级) [A类]
- D9-6: 模型选择更新(moka/claude-sonnet-4-6) [D类]
- D9-7: 调用方式更新(model参数) [D类]
- D9-8: 参考版本号

#### 文档10: spec/README.md (P0, ~5min)
4项变更(D10-1~D10-4): 版本号v4.0→v4.3, 功能数43→49, P0列表更新, 日期更新

#### 文档11: PROJECT_STATUS.md (P1, ~15min)
5项变更(D11-1~D11-5): PRD/技术设计版本, 当前阶段, 已完成功能, 下一步计划

#### 文档12: DOCUMENTATION_CHECKLIST.md (P2, ~10min)
引用版本号更新+新增检查项

### 工作量总览
| 类别 | 文档数 | 总工作量 |
|------|--------|----------|
| P0必须 | 7份(Database/API/Security/Algorithm/Test/LLM_Prompt/spec_README) | ~12.25h |
| P1重要 | 4份(UI_UX/Integration/Deployment/PROJECT_STATUS) | ~7.75h |
| P2可选 | 1份(DOCUMENTATION_CHECKLIST) | ~10min |
| **合计** | **12份** | **~23.5h** |

### 建议执行顺序（原方案3批次）
批次1(P0核心): Database_Design + API_Design + Security_Design + Algorithm_Design + Test_Plan + LLM_Prompt_Templates + spec/README ≈4h并行
批次2(P1重要): Integration_Design + Deployment_Guide + PROJECT_STATUS + UI_UX_Design ≈4h
批次3(P2可选): DOCUMENTATION_CHECKLIST ≈10min

### 4个关键决策点（需投票）
DEC-1: UI设计现在做还是等前端？选项A=先做线框图 / 选项B=等许总团队确定后再做
DEC-2: 12份全部更新还是只更新P0？选项A=P0七份先做完(+README=7份) / 选项B=全部12份一次到位
DEC-3: 文档版本号规则？选项A=统一跳到v2.0(表示与PRD v4.3对齐) / 选项B=递增(v1.3)
DEC-4: 过时内容处理？选项A=标注deprecated / 选项B=直接删除

### 各角色Review重点要求

#### PM角色重点:
1. 97项变更是否完整？有没有遗漏的用户视角变更？
2. 工作量估计(~23.5h)是否合理？
3. 三批次执行顺序是否合理？
4. DEC-1~DEC-4四个决策点的建议是什么？

#### Architect角色重点:
1. 文档间的依赖关系是否正确？（如Algorithm是否真的依赖DB设计？）
2. 版本号策略（统一v2.0 vs 递增）哪个更好？
3. 有没有技术层面遗漏的变更？

#### Security角色重点:
1. Security_Design的5项C类变更是否充分？
2. 有没有遗漏的安全相关更新点？

#### Tester角色重点:
1. Test_Plan的更新项是否覆盖了所有P0功能的测试需求？
2. 回归测试策略是否足够？

#### Coder角色重点:
1. 哪些文档对编码实施最关键？（排序）
2. 有没有文档可以标记为"过时"而不需要逐项更新？

#### DevOps角色重点:
1. Deployment_Guide的CI/CD和Docker更新是否完整？
2. 监控指标定义是否可操作？

#### UI Designer角色重点:
1. UI_UX_Design的11项变更是否完整？
2. 首页改版方案是否与PRD v4.3 §5.8一致？

### 输出要求
请每个角色给出：
1. 对12份文档的更新优先级确认/调整建议
2. 对DEC-1~DEC-4决策点投票（选A或B并附理由）
3. 最终共识建议：批次1/批次2具体包含哪些文档、总工作量最终确认、是否有文档可跳过
"""

def main():
    print("=" * 70)
    print("EventLink P1-P7 文档更新清单 — DevSquad 7角色全员Review共识")
    print("=" * 70)
    print(f"后端: {MOKA_MODEL} @ {MOKA_BASE_URL}")
    print(f"模式: consensus (全员共识)")
    print(f"角色: 全部7角色 (pm/architect/security/tester/coder/devops/ui-designer)")
    print("=" * 70)

    # 创建Moka AI后端
    backend = create_backend(
        "openai",  # 使用OpenAI兼容协议
        api_key=MOKA_API_KEY,
        base_url=MOKA_BASE_URL,
        model=MOKA_MODEL,
    )

    # 创建Dispatcher
    disp = MultiAgentDispatcher(
        llm_backend=backend,
        enable_warmup=True,
        enable_compression=True,
        enable_permission=True,
        enable_memory=True,
    )

    # 执行7角色共识Review
    roles = [
        "product-manager",
        "architect",
        "security",
        "tester",
        "solo-coder",
        "devops",
        "ui-designer",
    ]

    result = disp.dispatch(
        task_description=TASK_DESCRIPTION,
        roles=roles,
        mode="consensus",  # 强制共识模式
        dry_run=False,
        timeout_seconds=180,  # 超时180秒
    )

    # 输出结果
    print("\n" + "=" * 70)
    print("REVIEW结果")
    print("=" * 70)
    print(f"成功: {result.success}")
    print(f"耗时: {result.duration_seconds:.2f}s")
    print(f"参与角色: {result.matched_roles}")
    
    if result.errors:
        print(f"\n错误: {result.errors}")

    # 输出完整Markdown报告
    report = result.to_markdown()
    print("\n" + "=" * 70)
    print("完整共识报告")
    print("=" * 70)
    print(report)

    # 保存报告到文件
    output_path = "./docs/internal/EventLink_P1-P7_DevSquad共识报告.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n✅ 报告已保存至: {output_path}")

    # 清理
    disp.shutdown()
    
    return result.success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
