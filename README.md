# EventLink — AI 关联发现引擎

> **状态**: 探索期/规划中 (P1-P7 部分完成)
> **负责人**: 林总 (CarryMem 团队)
> **合作方**: 许总 (IAMHERE 数字名片)

## 一句话

数字名片 + AI 关联发现引擎 = 自动发现隐藏的商脉和人脉线索

## 快速导航

| 需要看什么 | 在哪里 |
|-----------|--------|
| 给许总的技术方案 | `docs/external/for_许总/EventLink_技术方案V3_网页版.html` |
| 团队共享文档 | `docs/external/for_team/` |
| 内部分析报告 | `docs/internal/` |
| 项目完整状态 | [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) (11阶段检查清单) |

## 目录结构

```
EventLink/
├── docs/
│   ├── PROJECT_STATUS.md          # ⭐ 11阶段生命周期总览（必读）
│   ├── internal/                  # 内部文档
│   ├── external/                  # 对外文档
│   │   ├── for_许总/              # 给合作方的交付物
│   │   └── for_team/             # 团队共享
│   ├── spec/                      # 待补充: PRD
│   ├── architecture/              # 待补充: ADR
│   ├── planning/                  # 待补充: 测试计划
│   └── design/                    # 待补充: 详细设计
├── scripts/                       # 工具脚本
├── archive/                       # 归档文件
└── data/                          # 运行时数据
```

## 当前进度 (17%)

```
P1需求 ✅ → P2架构 🟡 → P3技术 ✅ → P4数据 ✅ → P5交互 ✅ → P6安全 ✅ → P7测试 🟡
                                                                                    ↓
P8实施 ⬜ → P9测试 ⬜ → P10部署 ⬜ → P11运维 ⬜
```

**阻塞点**: 等待许总对技术方案的反馈确认

## 技术栈 (规划)

| 组件 | 选型 |
|------|------|
| API框架 | FastAPI (Python 3.11+) |
| 数据库 | PostgreSQL 15 + Redis 7 |
| 图算法 | NetworkX + igraph |
| 实体抽取 | Moka AI (Claude Sonnet) / spaCy降级 |
| 部署 | Docker Compose → K8s |

## 核心能力

1. **实体归一** — 判断"李总""李明""老李"是否同一人（含人工确认+撤回）
2. **关联发现** — 7种关系类型自动识别（校友/前同事/竞对/技术重叠等）
3. **提醒生成** — 3类提醒（商机⚪ / 风险🔴 / 背景🔵）
4. **分期落地** — 第一期基于自有数据，后续按需增强
