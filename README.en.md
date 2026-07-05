# PromiseLink — AI-Driven Personal Business Relationship Management Assistant

[English](README.en.md) | [中文](README.md) | [日本語](README.jp.md)

> **Slogan**: Make every connection more valuable
>
> **Positioning**: Build relationships first, then drive collaboration — an altruism-first personal business relationship management system

<p align="center">
  <a href="https://promiselink.cn"><img src="https://img.shields.io/badge/🌐_官网-promiselink.cn-blue?style=for-the-badge" alt="Website"></a>
  <br/>
  <a href="https://github.com/lulin70/PromiseLink/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/lulin70/PromiseLink/ci.yml?branch=main&label=CI&logo=github" alt="CI"></a>
  <img src="https://img.shields.io/badge/tests-1364%20passed-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/coverage-71%25-green" alt="Coverage">
  <img src="https://img.shields.io/badge/mypy-0%20errors-brightgreen" alt="mypy">
  <img src="https://img.shields.io/badge/ruff-0%20errors-brightgreen" alt="ruff">
  <img src="https://img.shields.io/badge/security-50%20tests%20passed-blue" alt="Security">
  <img src="https://img.shields.io/badge/perf-17%20tests%20passed-blue" alt="Performance">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/deploy-Local%20No%20Docker-success" alt="Deploy">
  <img src="https://img.shields.io/badge/license-AGPL%20v3-red" alt="License">
</p>

> **PromiseLink** is the **open-source basic edition** (AGPL v3) of the AI-driven personal business relationship management assistant.
> It provides the core loop: event entry → entity extraction → Todo generation → promise tracking → association discovery → dashboard.
>
> **Architectural layering**:
> - **Core algorithm layer** (entity resolution / Todo state machine / promise fulfillment / association discovery / dynamic scoring) — **pure algorithm implementation, no LLM dependency**, runs offline, auditable, reproducible
> - **LLM enhancement layer** (entity extraction / NLG response generation) — optional LLM enhancement, requires `LLM_API_KEY` (Moka AI / OpenAI / Anthropic, any one)
>
> **Not included**: voice input, voice query, email sync, WeChat forwarding, OCR business card scanning, private data management — these are Pro edition features.
> The basic edition can optionally connect to the Pro edition cloud gateway via `relay_client` to use cloud AI capabilities (requires Pro License).
> The frontend is Taro H5 (desktop browser widescreen first, mobile compatible).

**Topics**: `crm` `relationship-management` `ai-assistant` `fastapi` `taro` `sqlite-vec` `local-first` `agpl`

---

## 🌟 Why Choose PromiseLink

| Advantage | Proof | vs. Traditional CRM |
|------|---------|-------------|
| 🏭 **Industrial-grade quality** | 1364 tests passed / 71% coverage / mypy 0 / ruff 0 / 50 security tests / 17 performance tests | Most open-source CRMs have < 30% coverage |
| 🧠 **Core algorithm layer does not depend on LLM** | Entity resolution / Todo state machine / promise fulfillment / association discovery / dynamic scoring — pure algorithm implementation (NetworkX + RapidFuzz + numpy), runs offline, auditable | Mainstream AI-CRMs depend on GPT API across the full chain |
| 🚀 **Portable, zero deployment** | `pip install -e .` + `bash scripts/start.sh` ready to use, no Docker / K8s required | Similar tools require docker-compose |

> **Honest disclosure**: Entity extraction, NLG response generation, etc. require `LLM_API_KEY`; the core relationship management algorithms (5 modules) are pure algorithm implementations — when LLM is unavailable, the core loop still runs in degraded mode.

---

## 📑 Table of Contents

- [Quick Start](#quick-start)
- [30-Second Verification](#30-second-verification-no-llm-configuration-required)
- [Quality Metrics](#quality-metrics)
- [Core Capabilities](#core-capabilities)
- [Comparison with Mainstream Solutions](#comparison-with-mainstream-solutions)
- [Project Structure](#project-structure)
- [Documentation Index](#documentation-index)
- [Current Progress](#current-progress)
- [Tech Stack](#tech-stack)
- [Product Editions](#product-editions)
- [Verify Installation](#verify-installation)
- [Team](#team)
- [License](#license)

---

## Quick Start

> ⚡ **3 steps to start, 5 minutes to onboard, no Docker / no cloud account / data fully self-hosted locally**

```bash
# 1. Install dependencies
pip install -e '.[dev]'

# 2. Configure environment variables
cp .env.basic.example .env
# Edit .env and fill in LLM_API_KEY (any one of Moka AI / OpenAI / Anthropic)

# 3. Start the app (run locally directly, no Docker required)
python -m uvicorn promiselink.main:app --host 0.0.0.0 --port 8000
# Or use the one-click start script (recommended)
bash scripts/start.sh

# 4. Access
# API docs: http://localhost:8000/docs
# Frontend UI: http://localhost:8000
```

### 30-Second Verification (No LLM Configuration Required)

> No LLM API Key is needed to verify the project's engineering quality.

```bash
git clone https://github.com/lulin70/PromiseLink
cd PromiseLink
pip install -e '.[dev]'
pytest --co -q | tail -1   # Should show 1394 tests collected
pytest tests/test_security_comprehensive.py -q --no-cov   # 50 security tests
```

---

## Quality Metrics

| Metric       | Value                                                               |
| -------- | ---------------------------------------------------------------- |
| Test cases     | **1364 passed**, 30 skipped, 0 failed (incl. 50 relay_client robustness + 12 v5.6 corrections + 50 security + 17 performance + 6 real LLM E2E) |
| Code coverage    | **71%**                                                          |
| mypy type check | **0 errors** (112 source files all passed)                                             |
| ruff code check | **0 errors**                                                          |
| Security tests     | **50 all passed** (SQL injection / XSS / path traversal / JWT / privilege escalation / input validation / rate limiting)         |
| Performance tests     | **17 all passed** (API response < 50-500ms + concurrency + memory)                         |
| API routes    | **24 route files / 63 API endpoints / 53 paths**                              |
| Service modules     | **38**                                                          |
| Data models     | **8 files, 10 model classes**                                                  |
| Documentation version     | PRD v5.8 / Tech v3.2                                             |
| Software version     | v0.8.0-rc2                                                       |
| Product tier     | Basic (local free) / Pro (gateway relay) / Mini-program (mobile) / Custom (team)                      |
| Overall progress     | **89%** (Basic E2E 81/0/0 zero skip achieved)                              |

> **Layered coverage note**: The core algorithm layer (entity_resolution / todo_state_machine / promise_fulfillment / association_discovery / priority_scorer) has coverage higher than the project average of 71%, and does not depend on LLM — deterministic and reproducible.

---

## Core Capabilities

### Event Processing Pipeline (13 Steps)

```mermaid
graph LR
  A[Step01<br/>Event Validation+Input Classification] --> B[Step02<br/>Entity Extraction+Resolution]
  B --> C[Step03<br/>Entity Vectorization]
  C --> D[Step04<br/>Todo Generation<br/>6 types]
  D --> E[Step05<br/>Bidirectional Promise Analysis]
  E --> F[Step06<br/>Resource Overcommit Detection]
  F --> G[Step07<br/>Dynamic Priority Scoring]
  G --> H[Step08<br/>Notification Scheduling]
  H --> I[Step09<br/>Memory Storage]
  I --> J[Step10<br/>Association Discovery<br/>3 strategies]
  J --> K[Step11<br/>Association→Todo Generation]
  K --> L[Step12<br/>Relationship Brief Update]
  L --> M[Step13<br/>Event Completed]
```

**Architectural layering — algorithm layer decoupled from LLM layer**:

| Layer | Module | LLM Dependency | Description |
|------|------|---------|------|
| **Core algorithm layer** | `entity_resolution.py` | ❌ None | Entity resolution (5-step algorithm) |
| | `todo_state_machine.py` | ❌ None | Todo state machine |
| | `promise_fulfillment.py` | ❌ None | Promise fulfillment tracking |
| | `association_discovery.py` | ❌ None | Association discovery (3 strategies) |
| | `priority_scorer.py` | ❌ None | Dynamic priority scoring (4 dimensions) |
| **LLM enhancement layer** | `entity_extractor.py` | ✅ Required | Unstructured text → structured entities |
| | `todo_generator.py` | ✅ Required | Todo content generation |
| | `title_generator.py` | ✅ Required | Event title generation |

> The core algorithm layer is implemented with NetworkX + RapidFuzz + numpy — pure Python algorithms, independently unit-testable, runnable without LLM, deterministic and reproducible, with no hallucination risk.

**Todo types** (fog/mist color palette):

| Type                  | Color | Meaning   |
| ------------------- | -- | ---- |
| promise             | Fog green | Promise items |
| help                | Fog purple | Help suggestions |
| care                | Fog blue | Attention reminders |
| followup            | Fog gold | Follow-up |
| cooperation_signal  | Fog white | Cooperation signal |
| risk                | Smoke pink | Risk warning |

### Data Ingestion Layer (DataSourceAdapter)

- Manual input / CSV import (voice input / WeChat forwarding / email sync are Pro edition features)

### Insight Engine

- Dynamic priority scoring (4 dimensions: urgency × 0.4 + importance × 0.6)
- Implicit feedback learning (completion order → relationship weight)
- Scenario matching (DependencyAnalyzer + ContextMatcher)

---

## Comparison with Mainstream Solutions

| Capability | PromiseLink Basic Edition | Traditional CRM | SaaS AI-CRM |
|------|-------------------|----------|-------------|
| Local offline operation | ✅ No Docker | ⚠️ Some require Docker | ❌ Must be online |
| Core algorithm does not depend on LLM | ✅ Pure algorithm | ✅ No LLM | ❌ Full-chain dependency |
| Promise / Todo relationship tracking | ✅ 6-type Todo state machine | ❌ Tasks only | ⚠️ Simple |
| Association discovery | ✅ 3 strategies | ❌ | ⚠️ LLM-generated |
| Data ownership | ✅ 100% local SQLite | ⚠️ | ❌ Cloud |
| Price | Free (AGPL v3) | $$$$ | $$$/month |

---

## Project Structure

<details>
<summary>📁 Click to expand full project structure</summary>

```
PromiseLink/
├── src/promiselink/              # Application source code
│   ├── models/                 # Data models (8 model files, 10 model classes)
│   │   ├── entity.py           # Person entity
│   │   ├── event.py            # Interaction event
│   │   ├── todo.py             # Action reminder (6 types)
│   │   ├── association.py      # Association discovery
│   │   └── relationship_brief.py  # Relationship brief
│   ├── api/v1/                 # REST API (24 route files)
│   │   ├── health.py           # Health check
│   │   ├── events.py           # Event CRUD + Pipeline trigger
│   │   ├── entities.py         # Entity management
│   │   ├── todos.py            # Todo management
│   │   ├── associations.py     # Association query
│   │   ├── relationship_briefs.py  # Relationship brief
│   │   ├── dashboard.py        # Data dashboard
│   │   ├── export.py           # Data export
│   │   ├── demand_input.py     # Demand input
│   │   └── auth.py             # Authentication
│   ├── services/               # Core engine (38 modules)
│   │   ├── event_pipeline.py   # 13-step event processing pipeline
│   │   ├── entity_extractor.py    # LLM entity extraction
│   │   ├── entity_resolution.py    # Entity resolution (5-step algorithm, no LLM)
│   │   ├── todo_generator.py       # Todo generation (6-type strategy)
│   │   ├── todo_state_machine.py   # Todo state machine (no LLM)
│   │   ├── promise_fulfillment.py  # Promise fulfillment tracking (no LLM)
│   │   ├── association_discovery.py # Association discovery (3 strategies, no LLM)
│   │   ├── priority_scorer.py      # Dynamic priority scoring (no LLM)
│   │   ├── llm_client.py           # LLM client (Moka AI)
│   │   ├── semantic_search.py      # Vector semantic search
│   │   ├── memory_provider.py      # CarryMem integration
│   │   └── ...                     # (20+ other service modules)
│   ├── core/                    # Infrastructure
│   │   ├── crypto.py           # Encryption (HMAC-SHA256 + field encryption)
│   │   ├── exceptions.py       # Three-layer exception system
│   │   ├── natural_date.py     # Natural date parsing
│   │   └── logging.py / redis.py / wechat.py
│   ├── prompts/                # LLM Prompt templates
│   └── main.py                 # FastAPI entry
├── docs/                       # Documentation
├── tests/                      # Tests (67 files / 1394 cases)
├── data/                       # SQLite data storage
├── scripts/                    # One-click install/start scripts + E2E tests
└── frontend/                   # Taro H5 frontend
```

</details>

---

## Documentation Index

### Core Documents

- [PRD v5.8](docs/spec/PRD_v1.md) - Product Requirements Document
- [Technical Design v3.2](docs/architecture/PromiseLink_技术设计_v1.md) - Complete technical solution
- [Project Status](docs/PROJECT_STATUS.md) - 11-stage lifecycle tracking
- [QUICKSTART](QUICKSTART.md) - Quick start guide (incl. config reference and FAQ)
- [Setup Guide](docs/deliverables/README_SETUP.md) - Installation instructions (points to QUICKSTART)

### Detailed Design Documents

- [Database Design v3.0](docs/design/Database_Design_v1.md)
- [API Design v3.1](docs/design/API_Design_v1.md)
- [Algorithm Design v2.8](docs/design/Algorithm_Design_v1.md)
- [Test Plan v5.1](docs/design/Test_Plan_v1.md)
- [Integration Design v2.9](docs/design/Integration_Design_v1.md)
- [Deployment Guide v0.5.0](docs/design/Deployment_Guide.md)

> Security design documents (Security_Design series, THREAT_MODEL) have been migrated to the Pro edition private repository [PromiseLink-Pro](https://github.com/lulin70/PromiseLink-Pro).

---

## Current Progress

### ✅ Completed (P1-P9)

- [x] PRD v5.2 (relationship management core loop + vectorized semantic capability)
- [x] Technical design v3.2 (Insight Engine + DataSourceAdapter + vector semantics)
- [x] P0 core algorithms fully implemented (entity resolution / promise fulfillment / state machine / association discovery / dynamic scoring)
- [x] FastAPI complete implementation (24 route files / 63 API endpoints / 53 paths)
- [x] 38 service modules (Pipeline / NLG / SemanticSearch / MemoryProvider, etc.)
- [x] 8 model files (entity / event / todo / association / relationship_brief / scheduled_event / reminder / score_audit_log)
- [x] DataSourceAdapter abstraction layer (manual / CSV; voice / WeChat / email are Pro edition features)
- [x] CarryMem protocol decoupling (NullMemoryProvider graceful degradation)
- [x] Encryption system (HMAC-SHA256 + field-level encryption + row-level security)
- [x] 67 test files / **1394 test cases** (incl. 50 relay_client robustness + 12 v5.6 corrections + 6 real LLM E2E) / **71% coverage**
- [x] CI/CD + Alembic ready
- [x] PoC Demo 4/4 scenarios passed
- [x] One-click install / start scripts (run locally directly, no Docker required)
- [x] Taro H5 frontend packaged and released

### 🔴 Not Started

- [ ] Pro edition: gateway relay development (SQLite + relay gateway)
- [ ] Custom edition: team collaboration features (PG + Redis + multi-tenant)

---

## Tech Stack

| Layer      | Technology                                                                     |
| ------- | ---------------------------------------------------------------------- |
| **Framework**  | FastAPI 0.109+ (Python 3.11+)                                          |
| **Database** | SQLite (basic edition + Pro edition long-term plan) / PostgreSQL 15 (custom edition)                         |
| **ORM** | SQLAlchemy 2.0+ (async)                                                |
| **LLM** | Moka AI (Claude Sonnet 4.6) / OpenAI (GPT-5.5) / Anthropic             |
| **Vector**  | sqlite-vec (basic edition + Pro edition) / pgvector (custom edition)                                  |
| **Cache**  | Redis (custom edition)                                                            |
| **Algorithm**  | NetworkX + RapidFuzz + numpy (core algorithm layer, no LLM dependency)                            |
| **Deployment**  | Basic edition: run locally directly (no Docker) / Pro edition: Docker + gateway relay / Custom edition: Docker Compose + K8s |

---

## Verify Installation

```bash
# Health check
curl http://localhost:8000/api/v1/health

# Create an interaction event (triggers the full Pipeline)
curl -X POST http://localhost:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "event_type": "meeting",
    "source": "manual",
    "raw_text": "Today I talked with Mr. Zhang about cooperation; he said he needs a technical proposal next week"
  }'

# Query entity list
curl http://localhost:8000/api/v1/entities \
  -H "Authorization: Bearer <token>"

# Query Todo list (with dynamic priority sorting)
curl http://localhost:8000/api/v1/todos \
  -H "Authorization: Bearer <token>"

# Semantic search
curl "http://localhost:8000/api/v1/entities?search=technical cooperation" \
  -H "Authorization: Bearer <token>"
```

---

## Product Editions

| Edition | Repository | Positioning | Price | Deployment |
|------|------|------|------|----------|
| **Basic Edition** | [PromiseLink](https://github.com/lulin70/PromiseLink) (🌐 public AGPL v3) | Local free, plain-text interaction, desktop widescreen | Free | Run locally directly (no Docker) |
| **Pro Edition** | [PromiseLink-Pro](https://github.com/lulin70/PromiseLink-Pro) (🔒 private commercial License) | Cloud AI gateway + voice / email / OCR / privacy management | ¥29/month (early bird) / ¥49/month (regular) | Docker + cloud gateway |
| **Mini-Program** | [PromiseLink-miniapp](https://github.com/lulin70/PromiseLink-miniapp) (🔒 private commercial License) | WeChat mini-program, mobile portrait, Pro edition mobile client | Bundled with Pro | WeChat mini-program platform |
| **Custom Edition** | (not public) | Sales team collaboration, multi-tenant | Custom quote | Cloud Docker Compose + K8s |

> The basic edition uses plain-text interaction and does not include voice or image scanning features. The Pro edition depends on cloud service credentials.
> The basic edition can optionally connect to the Pro edition cloud gateway via `relay_client` to use cloud AI capabilities (requires Pro License).

---

## Team

| Role | Member | GitHub |
|------|------|--------|
| Project Lead | Mr. Lin (CarryMem Team) | [@lulin70](https://github.com/lulin70) |
| Product Advisors | Mr. Xu / Mr. Li / Mr. Jian | — |
| Design | Sophia J Lin | — |
| Partner | IAMHERE Digital Business Cards | — |

---

## License

AGPL-3.0 — see the [LICENSE](LICENSE) file for details
