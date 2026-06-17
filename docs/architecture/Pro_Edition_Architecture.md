# PromiseLink 专业版架构设计 (Pro Edition Architecture)

> **版本**: v1.0
> **日期**: 2026-06-17
> **对应PRD**: v5.2
> **对应技术设计**: v3.2 (§8.7 网关中继架构)
> **基础版版本**: v0.5.4 (成熟度 92/100)
> **许可证**: AGPL v3 (基础版开源) / 商业许可 (专业版闭源网关)

---

## 0. 文档定位与读者

本文档是 PromiseLink 专业版（Pro Edition）的**架构设计权威文档**，面向：
- 架构师：理解专业版整体架构和技术选型决策
- 后端开发：实现云端AI网关、媒体处理、邮件同步等模块
- DevOps：部署专业版服务（网关 + 本地Docker）
- 产品经理：理解专业版能力边界和商业模型

**与现有文档关系**：
- `PromiseLink_技术设计_v1.md` §8.7 定义了网关中继架构的协议层设计，本文档在此基础上扩展为完整的专业版架构
- `edition_architecture.md` 定义了基础版/专业版的版本对比和安全模型，本文档是其专业版部分的详细展开
- `基础版与专业版开发计划_v1.0.md` 提供了高层计划，本文档的姊妹篇 `Pro_Edition_Implementation_Plan.md` 提供分阶段详细计划

---

## 1. 专业版定位与核心价值

### 1.1 产品定位

| 维度 | 基础版 (Basic) | 专业版 (Pro) |
|------|---------------|--------------|
| **目标用户** | 技术用户（开发者/极客） | 非技术用户（商务人士如许总） |
| **核心痛点** | 愿意自配API Key，追求隐私 | 不懂技术，要"开箱即用" |
| **定价** | 免费 (AGPL v3 开源) | ¥29/月(早鸟) / ¥49/月(常规) |
| **AI能力** | 用户自备LLM API Key | 云端AI网关提供（用户无需配置） |
| **数据位置** | 用户本地（数据从不出家门） | 用户本地（网关仅中继，不存业务数据） |
| **前端入口** | Taro H5（局域网浏览器） | 微信小程序（随时随地） |
| **输入方式** | 纯文本（手动输入+粘贴） | 文本+语音+名片扫描+邮件+微信转发+CSV |

### 1.2 核心价值主张

**"关系助手，随身携带"** — 专业版的核心价值是让非技术用户零配置享受AI能力：

1. **零配置AI** — 用户不需要申请/配置任何API Key，网关统一提供DeepSeek/Moka AI能力
2. **多模态输入** — 语音录入、名片扫描、邮件同步、微信转发、CSV批量导入
3. **随时随地访问** — 微信小程序为主入口，不受局域网限制
4. **隐私不妥协** — 业务数据始终在用户本地Docker，网关仅做加密中继，不解析不存储业务payload

### 1.3 商业模型

```
用户付费 ¥29/月 → 网关验证身份 → 放行AI调用 → 按月计量
                         ↓
                    AI成本 ~¥0.3/月/用户 (DeepSeek)
                    基础设施 ~¥510/月 (固定)
                    盈亏平衡点: ~18个付费用户
```

---

## 2. 专业版整体架构

### 2.1 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        微信小程序 (用户手机)                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │ 原生:语音录入 │  │ 原生:TTS播报 │  │ 原生:名片扫描│  │ H5:查询管理│ │
│  │ wx.startRecord│ │ 同声传译插件 │  │ wx.scanCode  │  │ WebView   │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └─────┬─────┘ │
└─────────┼──────────────────┼──────────────────┼────────────────┼──────┘
          │                  │                  │                │
          │     HTTPS        │                  │    临时授权码    │
          ▼                  ▼                  ▼                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   云端AI网关 (Cloud AI Gateway)                       │
│                   api.promiselink.com / gw.promiselink.ai             │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌──────────┐  ┌──────┐ │
│  │中继路由器 │  │ AI代理层   │  │许可验证   │  │用量计费   │  │API池 │ │
│  │WebSocket │  │LLM/ASR/TTS│  │PRO_LICENSE│  │Token计数  │  │Key轮 │ │
│  │连接映射  │  │OCR代理    │  │JWT验证    │  │红黄绿灯   │  │询限流│ │
│  └────┬─────┘  └─────┬─────┘  └──────────┘  └──────────┘  └──────┘ │
│       │               │                                               │
│       │    ┌──────────┼──────────┐                                    │
│       │    ▼          ▼          ▼                                    │
│       │  DeepSeek   Moka AI   阿里云语音  ← 外部AI服务                  │
│       │  API        API        API                                    │
└───────┼───────────────────────────────────────────────────────────────┘
        │ WebSocket (WSS长连接, 用户PC主动出站)
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                用户本地Docker (家用电脑)                               │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    FastAPI 业务服务                              │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │ │
│  │  │Event     │ │Query     │ │Todo      │ │Insight   │          │ │
│  │  │Ingest    │ │Service   │ │Service   │ │Engine    │          │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │ │
│  │  │Voice     │ │Media     │ │Email     │ │Privacy   │ ← Pro模块│ │
│  │  │Assistant │ │Processor │ │Sync      │ │Manager   │          │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │ │
│  │  ┌──────────────────────────────────────────────────────────┐  │ │
│  │  │  relay_client (嵌入式后台Task, 专业版自动启动)              │  │ │
│  │  │  ├── WSS连接管理 (心跳30s + 指数退避重连)                  │  │ │
│  │  │  ├── AI调用代理 (X-AI-Call标记 → 网关代理)                 │  │ │
│  │  │  └── JWT自动刷新 (无感续期)                                │  │ │
│  │  └──────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────┘ │
│  ┌──────────┐  ┌──────────────┐  ┌──────────┐                      │
│  │ SQLite   │  │ 本地Embedding │  │ Taro H5  │                      │
│  │ (业务数据)│  │ (向量检索)    │  │ (静态文件)│                      │
│  └──────────┘  └──────────────┘  └──────────┘                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 三层架构职责划分

| 层级 | 组件 | 职责 | 数据存储 |
|------|------|------|----------|
| **L1 小程序层** | 微信小程序 | 用户交互、语音录入、TTS播报、名片扫描 | 无（仅缓存token） |
| **L2 网关层** | 云端AI网关 | 中继转发、AI代理、许可验证、用量计费 | 用户账户+用量记录（PG） |
| **L3 本地层** | 本地Docker | 业务逻辑、数据存储、AI调用发起 | SQLite（业务数据） |

### 2.3 核心设计原则

1. **网关无状态中继** — 网关不存业务数据，只做加密转发+AI代理+计数限流，可随时替换/重启
2. **用户PC主动出站** — 用户PC主动连网关（WSS出站），无需公网IP、无需端口映射
3. **同一套代码库** — 基础版和专业版共用代码，通过 `APP_EDITION` 配置区分，Pro路由条件注册
4. **AI调用经网关代理** — 专业版用户不持有LLM API Key，所有AI调用经网关代理（核心商业价值）
5. **隐私优先** — 网关仅传输JWT令牌（用户ID+付费状态），不传输关系数据/事件/实体/AI对话内容

---

## 3. 功能模块技术选型

### 3.1 语音助手 (ASR/NLU)

#### 3.1.1 ASR (语音转文字)

| 方案 | 类型 | 优点 | 缺点 | 成本 | 推荐度 |
|------|------|------|------|------|--------|
| **Moka AI Whisper** | 云端API | OpenAI兼容、中文效果好、无需本地GPU | 依赖网络 | 按量计费 | ⭐⭐⭐⭐⭐ **首选** |
| Whisper本地 | 本地推理 | 完全离线、零API成本 | 需GPU、中文效果一般、Docker镜像大 | 免费(算力) | ⭐⭐⭐ 降级方案 |
| 阿里云语音识别 | 云端API | 中文最优、实时流式ASR | 需单独接入、非OpenAI兼容 | 按量计费 | ⭐⭐⭐ 备选 |

**推荐方案**: Moka AI Whisper (首选) + 本地Whisper (降级)

**选型理由**:
- Moka AI Whisper 与现有 LLM API Key 共享认证体系（OpenAI兼容），零额外配置
- 已在 `asr_service.py` 实现，含自动降级到本地whisper的fallback逻辑
- 中文识别效果满足商务场景需求（会议纪要、语音录入）
- 微信小程序端可使用微信同声传译插件作为前端ASR（免费），后端ASR处理音频文件上传场景

**已实现状态**: ✅ `src/promiselink/services/asr_service.py` 已完整实现

#### 3.1.2 NLU (自然语言理解/意图识别)

| 方案 | 类型 | 优点 | 缺点 | 推荐度 |
|------|------|------|------|--------|
| **LLM意图分类** | 云端LLM | 灵活、支持复杂意图、零规则维护 | 依赖LLM、有延迟 | ⭐⭐⭐⭐⭐ **首选** |
| 规则引擎 | 本地 | 快速、零成本 | 僵化、难维护 | ⭐⭐⭐ 辅助 |

**推荐方案**: LLM意图分类 (主) + 规则引擎 (快速路径优化)

**意图分类体系**:
- `query_contact` — 查询人脉（"张总的电话是多少"）
- `query_promise` — 查询承诺（"我答应过李总什么"）
- `query_todo` — 查询待办（"今天有什么待办"）
- `query_schedule` — 查询日程（"明天有什么安排"）
- `create_event` — 创建事件（"记录一下今天和王总吃了饭"）
- `unknown` — 未识别（降级为文本搜索）

**已实现状态**: ✅ `src/promiselink/services/nlu_intent_classifier.py` 已实现

#### 3.1.3 语音查询响应

**数据流**:
```
用户语音 → ASR转文字 → NLU意图识别 → 路由到对应查询服务 → NLG生成回复 → TTS播报
```

**已实现状态**: ✅ `src/promiselink/services/voice_query_service.py` + `nlg_service.py` 已实现

---

### 3.2 媒体处理 (ASR/TTS/OCR)

#### 3.2.1 TTS (文字转语音)

| 方案 | 类型 | 优点 | 缺点 | 成本 | 推荐度 |
|------|------|------|------|------|--------|
| **Moka AI TTS** | 云端API | OpenAI兼容、音质好、与LLM统一认证 | 依赖网络 | 按量计费 | ⭐⭐⭐⭐⭐ **首选** |
| Edge-TTS | 免费API | 完全免费、音质尚可 | 非官方API、稳定性无保证 | 免费 | ⭐⭐⭐ 备选 |
| 微信同声传译 | 小程序原生 | 免费、小程序内直接调用 | 仅小程序可用、音质一般 | 免费 | ⭐⭐⭐⭐ 前端首选 |
| 阿里云语音合成 | 云端API | 中文音质最优、支持多音色 | 需单独接入 | 按量计费 | ⭐⭐⭐ 备选 |

**推荐方案**: 微信同声传译插件 (小程序前端) + Moka AI TTS (后端音频文件生成)

**选型理由**:
- 小程序内TTS播报走微信同声传译插件（免费、原生体验好、无需网络往返）
- 后端TTS（如生成音频文件供下载）走Moka AI TTS（与LLM统一认证）
- Edge-TTS作为免费降级方案，但不作为生产首选（稳定性风险）

**已实现状态**: ✅ `src/promiselink/services/tts_service.py` 已实现（Moka AI TTS）

#### 3.2.2 OCR (图片文字识别)

| 方案 | 类型 | 优点 | 缺点 | 成本 | 推荐度 |
|------|------|------|------|------|--------|
| **Moka AI Vision** | 云端LLM | 结构化提取、理解语义、与LLM统一 | 依赖网络、有延迟 | 按量计费 | ⭐⭐⭐⭐⭐ **首选** |
| PaddleOCR | 本地推理 | 完全离线、中文OCR强、开源 | 仅文字提取无语义理解、Docker镜像大 | 免费(算力) | ⭐⭐⭐⭐ 降级方案 |
| 腾讯云OCR | 云端API | 中文OCR最优、名片专用模板 | 需单独接入、非OpenAI兼容 | 按量计费 | ⭐⭐⭐ 备选 |

**推荐方案**: Moka AI Vision (首选) + PaddleOCR (离线降级)

**选型理由**:
- Moka AI Vision 不仅能提取文字，还能直接结构化（人名/公司/职位/电话/邮箱），省去二次解析
- 已在 `ocr_service.py` 实现，使用Vision API + 结构化JSON输出prompt
- PaddleOCR作为完全离线降级方案（基础版用户无网络时使用）

**已实现状态**: ✅ `src/promiselink/services/ocr_service.py` 已实现（Moka AI Vision）

#### 3.2.3 媒体处理统一接口

```
POST /api/v1/media/asr   — 音频文件上传 → 文字
POST /api/v1/media/tts   — 文字 → 音频文件
POST /api/v1/media/ocr   — 图片上传 → 结构化文字
```

**已实现状态**: ✅ `src/promiselink/api/v1/media.py` 已实现

---

### 3.3 邮件同步

#### 3.3.1 技术选型

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **Python imaplib** | 标准库、零依赖、SSL/TLS支持 | 同步API、需手动管理连接 | ⭐⭐⭐⭐⭐ **首选** |
| aioimaplib | 异步IMAP | 非标准库、社区维护 | ⭐⭐⭐ 备选 |
| Microsoft Graph API | Exchange原生 | 仅限Outlook/Exchange | ⭐⭐⭐ 特定场景 |

**推荐方案**: Python imaplib (标准库)

**选型理由**:
- 标准库零依赖，Docker镜像不增大
- 支持SSL/TLS加密连接，满足安全要求
- 已在 `email_adapter.py` 实现，含邮件解析（RFC 2047头解码、multipart正文提取）
- Phase 1使用应用专用密码（App Password），Phase 2考虑OAuth2

#### 3.3.2 邮件处理流程

```
IMAP服务器 → 拉取未读邮件 → 解析邮件头/正文/附件
                                    ↓
                            转换为RawEvent
                                    ↓
                        进入Event Pipeline (复用基础版)
                                    ↓
                    实体抽取 + Todo生成 + 关联发现
```

**已实现状态**: ✅ `src/promiselink/services/email_adapter.py` 已实现

---

### 3.4 微信转发

#### 3.4.1 技术选型

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **规则解析 (正则)** | 零LLM依赖、毫秒级、可预测 | 格式固定、容错有限 | ⭐⭐⭐⭐⭐ **首选** |
| LLM解析 | 灵活、容错强 | 有延迟、有成本 | ⭐⭐⭐ 增强 |
| 企业微信API | 结构化数据 | 需企业微信环境 | ⭐⭐ 特定场景 |

**推荐方案**: 规则解析 (主) + LLM增强 (复杂场景)

**选型理由**:
- 微信转发消息格式相对固定（"名字 时间\n内容"），正则解析高效可靠
- 已在 `wechat_forward_adapter.py` 实现，支持群聊和单聊两种格式
- 零LLM依赖，基础版也可使用（但路由仅专业版注册）

**已实现状态**: ✅ `src/promiselink/services/wechat_forward_adapter.py` 已实现

#### 3.4.2 处理流程

```
用户长按微信消息 → 转发到小程序 → 粘贴文本
                                        ↓
                            规则解析 (正则匹配说话人+时间+内容)
                                        ↓
                                提取ChatMessage列表
                                        ↓
                            转换为Event (raw_text存储全文)
                                        ↓
                        进入Event Pipeline (实体抽取+Todo生成)
```

---

### 3.5 CSV批量导入

#### 3.5.1 技术选型

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **Python csv + pandas** | 标准库+强大数据处理 | pandas增加镜像体积 | ⭐⭐⭐⭐ **首选** |
| 纯csv标准库 | 零依赖 | 大文件处理弱 | ⭐⭐⭐ 轻量备选 |

**推荐方案**: Python csv标准库 (小文件) + pandas (大文件可选)

#### 3.5.2 导入流程

```
CSV文件上传 → 解析预览 (前10行) → 用户确认列映射
                                        ↓
                            批量解析为人脉/事件数据
                                        ↓
                        去重检查 (按姓名+电话/邮箱)
                                        ↓
                    批量写入 + 实体归一 + 关联发现
                                        ↓
                            返回导入结果报告
```

**已实现状态**: ✅ `src/promiselink/api/v1/import_csv.py` 已实现

---

### 3.6 隐私数据管理

#### 3.6.1 技术选型

| 能力 | 方案 | 选型理由 |
|------|------|----------|
| **字段加密** | AES-256-GCM (cryptography库) | 工业标准、认证加密、已实现 |
| **密钥派生** | PBKDF2-SHA256 (100K迭代) | 标准库、抗暴力破解 |
| **脱敏显示** | 运行时掩码 (不修改存储) | 灵活、可配置脱敏级别 |
| **审计日志** | 结构化日志 (structlog) | 与现有日志体系统一 |

#### 3.6.2 加密策略

```
敏感字段 (phone, email) → AES-256-GCM加密 → "ENC:" + base64(nonce+ciphertext) → 存储
                                          ↓
读取时 → 检测"ENC:"前缀 → 解密 → 返回明文 (API层) 或 脱敏 (展示层)
```

**密钥独立性**: `pii_encryption_key` 独立于 `secret_key`（JWT签名），即使JWT密钥泄露，PII数据仍安全。

**已实现状态**: ✅ `src/promiselink/core/crypto.py` 已实现（AES-256-GCM + PBKDF2）

#### 3.6.3 数据访问审计

```
用户操作 (查看/导出/删除) → 审计日志记录
    ├── user_id: 操作者
    ├── action: view/export/delete
    ├── resource: entity/event/todo
    ├── resource_id: 资源ID
    ├── timestamp: 操作时间
    └── ip: 来源IP (经网关时为网关IP)
```

**已实现状态**: ✅ `src/promiselink/api/v1/privacy.py` 已实现（GDPR端点：数据摘要/删除/导出）

---

## 4. 云端AI网关设计 (核心)

> **专业版的核心价值**：用户不需要自配LLM API Key，由网关统一提供AI能力并计费。

### 4.1 网关架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    云端AI网关 (Cloud AI Gateway)                  │
│                    部署: api.promiselink.com                     │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    接入层 (Nginx + TLS)                    │   │
│  │  HTTPS终止 + WSS升级 + 请求路由                           │   │
│  └──────────────────────┬───────────────────────────────────┘   │
│                         │                                        │
│  ┌──────────────────────▼───────────────────────────────────┐   │
│  │                    网关核心 (FastAPI)                      │   │
│  │                                                            │   │
│  │  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌──────────┐ │   │
│  │  │中继路由器 │  │ AI代理层   │  │许可验证   │  │用量计费   │ │   │
│  │  │          │  │           │  │           │  │           │ │   │
│  │  │WebSocket │  │LLM代理    │  │PRO_LICENSE│  │Token计数  │ │   │
│  │  │连接映射  │  │ASR代理    │  │JWT验证    │  │红黄绿灯   │ │   │
│  │  │请求转发  │  │TTS代理    │  │速率限制   │  │月度配额   │ │   │
│  │  │响应回传  │  │OCR代理    │  │           │  │           │ │   │
│  │  └────┬─────┘  └─────┬─────┘  └──────────┘  └──────────┘ │   │
│  │       │               │                                    │   │
│  │       │    ┌──────────┼──────────┐                         │   │
│  │       │    ▼          ▼          ▼                         │   │
│  │       │  ┌──────────────────────────────┐                  │   │
│  │       │  │      API Key 池管理器          │                  │   │
│  │       │  │  ├── Key1 (DeepSeek) ── 健康率 │                  │   │
│  │       │  │  ├── Key2 (DeepSeek) ── 健康率 │                  │   │
│  │       │  │  ├── Key3 (Moka AI) ── 健康率  │                  │   │
│  │       │  │  └── 轮询 + 限流 + 熔断        │                  │   │
│  │       │  └──────────────────────────────┘                  │   │
│  │       │                                                  │   │
│  └───────┼──────────────────────────────────────────────────┘   │
│          │                                                       │
│  ┌───────▼──────────────────────────────────────────────────┐   │
│  │                    数据层 (PostgreSQL + Redis)             │   │
│  │  ├── PG: 用户账户 + 许可证 + 用量记录 + 审计日志           │   │
│  │  └── Redis: WebSocket连接映射 + JWT缓存 + 限流计数器       │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
          │                                        │
          │ WSS (用户PC主动出站)                     │ HTTPS (小程序直连)
          ▼                                        ▼
   用户本地Docker                              微信小程序
```

### 4.2 API Key 池管理

#### 4.2.1 设计目标

- **高可用**: 单个Key限流/失效时自动切换到其他Key
- **负载均衡**: 多Key轮询，避免单Key过载
- **成本控制**: 监控每个Key的用量，接近额度上限时预警
- **熔断降级**: Key连续失败时熔断，定时探活恢复

#### 4.2.2 Key池数据结构

```python
# 网关侧 Key 池管理 (伪代码)
class APIKeyPool:
    """LLM API Key 池管理器"""

    keys: list[APIKeyEntry]  # 多个Key条目

class APIKeyEntry:
    key_id: str              # Key标识
    provider: str            # deepseek / moka_ai / openai
    api_key: str             # 实际Key (加密存储)
    weight: int              # 轮询权重
    health: float            # 健康率 (0.0-1.0)
    rpm_limit: int           # 每分钟请求上限
    tpm_limit: int           # 每分钟Token上限
    current_rpm: int         # 当前RPM (Redis计数)
    current_tpm: int         # 当前TPM (Redis计数)
    status: str              # active / rate_limited / circuit_open / disabled
    last_error: str | None   # 最近错误
    cooldown_until: datetime | None  # 冷却截止时间
```

#### 4.2.3 轮询策略

```
请求到达 → 过滤可用Key (status=active 且 未超限)
                ↓
        按权重 + 健康率加权随机选择
                ↓
        调用LLM API → 成功 → 更新健康率(+)
                     → 429限流 → 标记rate_limited + 冷却60s
                     → 5xx错误 → 更新健康率(-) → 连续3次失败则熔断
                     → 超时 → 更新健康率(-)
                ↓
        所有Key不可用 → 返回503 + 降级提示
```

#### 4.2.4 熔断与恢复

| 状态 | 触发条件 | 恢复条件 |
|------|----------|----------|
| `active` | 默认状态 | - |
| `rate_limited` | 收到429 | 冷却60s后自动恢复 |
| `circuit_open` | 连续3次5xx错误 | 探活定时器每5分钟尝试一次 |
| `disabled` | 手动禁用 / Key失效 | 管理员手动启用 |

### 4.3 用户许可验证

#### 4.3.1 PRO_LICENSE_KEY 验证流程

```
步骤1: 用户付费 → 支付平台回调 → 网关生成 PRO_LICENSE_KEY
步骤2: 用户在小程序输入 LICENSE_KEY → 网关验证 → 激活专业版
步骤3: 网关签发 JWT (含 user_id + plan_type=pro + exp)
步骤4: 本地Docker的 relay_client 携带JWT连接网关 (WSS)
步骤5: 网关验证JWT → 建立WebSocket映射 → 后续请求放行
步骤6: JWT即将过期 → relay_client自动刷新 → 无感续期
```

#### 4.3.2 JWT Payload 结构

```json
{
  "user_id": "u_xxx",
  "plan_type": "pro",
  "license_key": "PL-PRO-xxxx-xxxx",
  "exp": 1718123456,
  "iat": 1718037056
}
```

#### 4.3.3 许可证数据模型

```sql
-- 网关侧 PostgreSQL 表结构
CREATE TABLE users (
    user_id          VARCHAR(64) PRIMARY KEY,
    wechat_openid    VARCHAR(128) UNIQUE,      -- 微信登录绑定
    nickname         VARCHAR(128),
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE licenses (
    license_key      VARCHAR(64) PRIMARY KEY,  -- PL-PRO-xxxx-xxxx
    user_id          VARCHAR(64) REFERENCES users,
    plan_type        VARCHAR(16) DEFAULT 'pro', -- pro
    billing_cycle    VARCHAR(16) DEFAULT 'monthly',
    status           VARCHAR(16) DEFAULT 'active', -- active/expired/cancelled
    started_at       TIMESTAMP DEFAULT NOW(),
    expires_at       TIMESTAMP,                -- 订阅到期时间
    auto_renew       BOOLEAN DEFAULT FALSE,
    price_cny        DECIMAL(8,2) DEFAULT 29.00,
    early_bird       BOOLEAN DEFAULT FALSE
);

CREATE TABLE usage_records (
    id               BIGSERIAL PRIMARY KEY,
    user_id          VARCHAR(64) REFERENCES users,
    request_id       VARCHAR(64),
    provider         VARCHAR(32),              -- deepseek/moka_ai
    model            VARCHAR(64),
    input_tokens     INT DEFAULT 0,
    output_tokens    INT DEFAULT 0,
    total_tokens     INT DEFAULT 0,
    cost_cny         DECIMAL(10,6) DEFAULT 0,
    request_type     VARCHAR(32),              -- llm/asr/tts/ocr
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE monthly_usage (
    user_id          VARCHAR(64),
    year_month       VARCHAR(7),               -- 2026-06
    total_tokens     BIGINT DEFAULT 0,
    total_cost_cny   DECIMAL(10,4) DEFAULT 0,
    request_count    INT DEFAULT 0,
    status           VARCHAR(16) DEFAULT 'green', -- green/yellow/red
    PRIMARY KEY (user_id, year_month)
);
```

### 4.4 用量计费

#### 4.4.1 计费模型

| 维度 | 策略 | 说明 |
|------|------|------|
| **计费单位** | Token (LLM) / 次 (ASR/TTS/OCR) | LLM按Token，媒体按次 |
| **计费周期** | 自然月 | 每月1日重置配额 |
| **配额上限** | 按定价档位 | 早鸟¥29: 50万Token/月; 常规¥49: 100万Token/月 |
| **超额处理** | 降级而非停服 | 超额后AI调用拒绝，基础功能仍可用 |

#### 4.4.2 用量状态灯

| 状态 | 含义 | 触发条件 | UI表现 |
|------|------|----------|--------|
| 🟢 绿灯 | 本月额度充足 | 用量 < 80% | 正常使用 |
| 🟡 黄灯 | 额度即将用尽 | 80% ≤ 用量 < 100% | 提示"本月AI调用接近上限" |
| 🔴 红灯 | 额度已用尽 | 用量 ≥ 100% | 拒绝AI调用，降级提示 |

#### 4.4.3 计费流程

```
AI请求到达网关 → 验证JWT → 查询用户当月用量
                                ↓
                        判断状态灯:
                        🟢 绿灯 → 放行 → 调用LLM → 记录用量 → 返回
                        🟡 黄灯 → 放行 + 响应头警告 → 调用LLM → 记录用量 → 返回
                        🔴 红灯 → 拒绝 (503) → 返回降级提示
```

#### 4.4.4 用量查询API

```
GET /api/v1/billing/usage        — 查询当月用量
GET /api/v1/billing/history      — 查询历史用量
GET /api/v1/billing/subscription — 查询订阅状态
```

### 4.5 网关中继协议

#### 4.5.1 WebSocket长连接

- **方向**: 用户PC **主动连**网关（出站连接，无需公网IP）
- **协议**: `wss://gw.promiselink.ai/relay`
- **认证**: 连接时携带 `user_token`（JWT签名），网关验证后建立映射

#### 4.5.2 消息格式

```json
// 请求 (小程序→网关→本地Docker)
{
  "type": "request",
  "request_id": "uuid-v4",
  "user_token": "jwt-signed-token",
  "payload": {
    "method": "POST",
    "path": "/api/v1/events",
    "headers": {"Content-Type": "application/json"},
    "body": {"content": "今天和张总吃了午饭，聊了新项目合作"}
  }
}

// 响应 (本地Docker→网关→小程序)
{
  "type": "response",
  "request_id": "uuid-v4",
  "payload": {
    "status": 200,
    "body": {"event_id": "xxx", "entities": [...]}
  }
}

// AI调用请求 (本地Docker→网关→LLM API)
{
  "type": "ai_call",
  "request_id": "uuid-v4",
  "user_token": "jwt-signed-token",
  "payload": {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "..."}],
    "max_tokens": 2000
  }
}

// AI调用响应 (网关→本地Docker)
{
  "type": "ai_response",
  "request_id": "uuid-v4",
  "payload": {
    "status": 200,
    "body": {"content": "...", "usage": {"total_tokens": 1234}},
    "billing": {"tokens_deducted": 1234, "monthly_status": "green"}
  }
}
```

#### 4.5.3 心跳与重连

| 参数 | 值 | 说明 |
|------|----|------|
| 心跳间隔 | 30s | relay_client定时发送ping |
| 超时判定 | 60s无pong | 网关判定连接断开，清除映射 |
| 重连策略 | 指数退避 | 1s → 2s → 4s → 8s → 16s → 30s（上限） |
| 重连上限 | 无限 | 持续重连直到网关恢复 |

### 4.6 AI调用路径 (三场景模型)

| 场景 | 用户状态 | 入口 | AI后端 | Key来源 | 网络要求 |
|------|----------|------|--------|---------|----------|
| 场景1 | 纯基础版（未付费） | 浏览器局域网 | 本地模型/自带Key | 用户自备 | 完全离线可用 |
| 场景2 | 专业版 + 在家用浏览器 | 浏览器局域网 | 云端AI（我方Key） | 网关代理 | 需联网验证身份 |
| 场景3 | 专业版 + 出门用小程序 | 微信小程序 | 云端AI（我方Key） | 网关代理 | 正常路径 |

**场景2详细流程** (专业版用户在家用浏览器):
```
浏览器(H5) → 本地Docker(FastAPI)
                    ↓
          检测到专业版身份 (JWT已激活)
                    ↓
          标注 "AI调用" 请求头 X-AI-Call: true
                    ↓
          relay_client → 中继网关(AI代理) → DeepSeek API → 返回
                    ↓
          本地Docker组装响应 → 浏览器
```

**场景3详细流程** (专业版用户出门用小程序):
```
微信小程序 → 中继网关 → 本地Docker(业务逻辑)
                              ↓
                    标注 "AI调用" 请求头 X-AI-Call: true
                              ↓
                    中继网关(AI代理) → DeepSeek API → 返回
                              ↓
                    本地Docker组装响应 → 中继网关 → 微信小程序
```

---

## 5. 数据流设计

### 5.1 语音录入数据流

```
[小程序原生页面]
用户长按录音 → wx.startRecord() → 录音文件
                                        ↓
[本地Docker]
POST /api/v1/voice/sessions → 创建VoiceSession
                                        ↓
POST /api/v1/media/asr (上传音频) → ASR转文字
                                        ↓
[网关AI代理]
relay_client → 网关 → Moka AI Whisper API → 返回文字
                                        ↓
[本地Docker]
文字 → Event Pipeline (实体抽取+Todo生成+关联发现)
                                        ↓
返回事件创建结果 → 小程序显示"已记录"
```

### 5.2 语音查询数据流

```
[小程序原生页面]
用户语音提问 → wx.startRecord() → 录音文件
                                        ↓
[本地Docker]
POST /api/v1/voice/query (上传音频)
                                        ↓
ASR转文字 → "张总的电话是多少"
                                        ↓
NLU意图识别 → query_contact (经网关LLM代理)
                                        ↓
路由到Query Service → 查询Entity "张总"
                                        ↓
NLG生成回复 → "张总的电话是138xxxx1234"
                                        ↓
TTS合成音频 (经网关TTS代理 或 微信同声传译)
                                        ↓
返回文字+音频 → 小程序播报
```

### 5.3 邮件同步数据流

```
[定时任务 / 手动触发]
POST /api/v1/email/sync
                                        ↓
[本地Docker]
EmailAdapter → IMAP连接 → 拉取未读邮件
                                        ↓
解析邮件 (头/正文/附件) → 转换为RawEvent
                                        ↓
进入Event Pipeline (实体抽取+Todo生成)
                                        ↓
提取邮件联系人 → 创建/更新Entity
                                        ↓
返回同步结果 (新邮件数/新增实体数/新增Todo数)
```

### 5.4 微信转发数据流

```
[小程序]
用户长按微信消息 → 转发到PromiseLink小程序 → 粘贴文本
                                        ↓
POST /api/v1/wechat/forward {content: "..."}
                                        ↓
[本地Docker]
WeChatForwardAdapter → 正则解析 → ChatMessage列表
                                        ↓
转换为Event (raw_text存储全文)
                                        ↓
进入Event Pipeline (实体抽取+Todo生成)
                                        ↓
返回解析结果 (识别到N条消息/M个说话人)
```

### 5.5 CSV导入数据流

```
[小程序/H5]
用户上传CSV文件
                                        ↓
POST /api/v1/import/csv/preview → 解析前10行预览
                                        ↓
用户确认列映射 (姓名→name, 电话→phone, ...)
                                        ↓
POST /api/v1/import/csv/confirm → 批量解析
                                        ↓
去重检查 (按姓名+电话/邮箱)
                                        ↓
批量写入Entity + 触发实体归一
                                        ↓
返回导入报告 (成功N条/跳过M条/失败K条)
```

### 5.6 名片扫描数据流

```
[小程序原生页面]
wx.scanCode() / 拍照 → 图片文件
                                        ↓
POST /api/v1/media/ocr (上传图片)
                                        ↓
[网关AI代理]
relay_client → 网关 → Moka AI Vision API → 返回结构化JSON
                                        ↓
[本地Docker]
结构化数据 (names/companies/titles/phone/email)
                                        ↓
POST /api/v1/events (card_save事件)
                                        ↓
Event Pipeline (轻量实体匹配, 秒级)
                                        ↓
返回名片录入结果
```

---

## 6. 安全模型

### 6.1 四层防护体系

| 层级 | 措施 | 说明 |
|------|------|------|
| **L1 路由层** | 条件注册 | basic模式下Pro路由不存在（返回404，不暴露版本信息） |
| **L2 认证层** | JWT + PRO_LICENSE_KEY | 所有API需JWT认证，AI调用需专业版许可验证 |
| **L3 网络层** | HTTPS + WSS + 反向代理 | 仅暴露443端口，所有流量加密 |
| **L4 数据层** | 用户隔离 + PII加密 | 所有查询强制user_id过滤，敏感字段AES-256-GCM加密 |

### 6.2 专业版API Key验证

```python
# 专业版路由保护 (伪代码)
@app.middleware("http")
async def verify_pro_license(request: Request, call_next):
    # 仅对Pro路由验证
    if not is_pro_route(request.url.path):
        return await call_next(request)

    # 1. JWT验证 (基础认证)
    user_id = verify_jwt(request.headers.get("Authorization"))
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    # 2. 专业版许可验证 (仅AI调用相关路由)
    if is_ai_call_route(request.url.path):
        license_status = await check_pro_license(user_id)
        if license_status != "active":
            return JSONResponse(status_code=403, content={"error": "Pro license required"})

    return await call_next(request)
```

### 6.3 网关安全

| 威胁 | 防护措施 |
|------|----------|
| 伪造JWT | 网关持有签名密钥，验证签名+过期时间 |
| 重放攻击 | JWT含exp（15分钟）+ refresh机制 |
| API Key泄露 | Key仅存网关侧，用户侧零Key配置 |
| 用量篡改 | 用量记录在网关PG，用户侧无法篡改 |
| 中间人攻击 | 全链路HTTPS/WSS，证书由Let's Encrypt签发 |
| 网关被攻破 | 网关不存业务数据，仅存用户账户+用量，业务数据在用户本地 |

### 6.4 隐私保护声明

> ⚠️ **联网仅验证付费身份，不传关系数据**
>
> 专业版身份验证过程中，网络传输仅包含JWT令牌（用户ID+付费状态+有效期），**不传输任何关系数据、事件记录、实体信息或AI对话内容**。
>
> - 业务数据始终存储在用户本地Docker中
> - 网关仅做加密转发，不解析、不存储业务payload
> - AI调用经网关代理时，网关仅转发LLM请求/响应，不持久化对话内容
> - 用量计费仅记录Token数，不记录请求/响应内容

### 6.5 AGPL v3 合规

| 组件 | 许可证 | 合规策略 |
|------|--------|----------|
| 基础版代码 | AGPL v3 | 开源，任何人可使用/修改/分发 |
| 专业版网关代码 | 闭源 | 网关是独立服务，不修改基础版代码，不触发AGPL传染 |
| relay_client模块 | AGPL v3 | 随基础版开源，用户自行部署 |
| 前端小程序 | 闭源 | 独立前端，不链接基础版代码 |

**Open Core模型**: 基础版开源是隐私的技术保证（用户可审计代码确认数据不出本地），专业版闭源的是网关服务（商业价值在AI代理+计费，不在代码）。

---

## 7. 部署架构

### 7.1 网关部署 (云端VPS)

```yaml
# docker-compose.gateway.yml (网关侧)
version: '3.8'

services:
  gateway:
    build: ./gateway
    ports:
      - "443:443"   # HTTPS + WSS
    environment:
      - GATEWAY_SECRET_KEY=${GATEWAY_SECRET_KEY}
      - DATABASE_URL=postgresql://promiselink:${PG_PASSWORD}@postgres:5432/gateway
      - REDIS_URL=redis://redis:6379/0
      # LLM API Keys (加密存储在环境变量)
      - DEEPSEEK_API_KEY_1=${DEEPSEEK_API_KEY_1}
      - DEEPSEEK_API_KEY_2=${DEEPSEEK_API_KEY_2}
      - MOKA_AI_API_KEY=${MOKA_AI_API_KEY}
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_DB=gateway
      - POSTGRES_USER=promiselink
      - POSTGRES_PASSWORD=${PG_PASSWORD}
    volumes:
      - gateway_pg_data:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
    volumes:
      - gateway_redis_data:/data
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/gateway.conf:/etc/nginx/conf.d/default.conf
      - ./certs:/etc/nginx/certs
    depends_on:
      - gateway
    restart: unless-stopped

volumes:
  gateway_pg_data:
  gateway_redis_data:
```

### 7.2 本地Docker部署 (用户侧)

```yaml
# docker-compose.pro.yml (用户侧专业版)
version: '3.8'

services:
  promiselink-api:
    build: .
    environment:
      - APP_EDITION=pro                          # 专业版模式
      - RELAY_GATEWAY_URL=wss://gw.promiselink.ai/relay  # 网关地址
      - RELAY_USER_TOKEN=${RELAY_USER_TOKEN}     # JWT令牌
      - AI_MODE=relay                            # AI调用走网关代理
      - DATABASE_URL=sqlite:///./data/promiselink.db
      - SECRET_KEY=${SECRET_KEY}                 # 本地JWT签名密钥
      - PII_ENCRYPTION_KEY=${PII_ENCRYPTION_KEY} # PII加密密钥
      # 专业版不需要 LLM_API_KEY (走网关代理)
    volumes:
      - ./data:/app/data
    restart: unless-stopped

  promiselink-web:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./frontend/dist:/usr/share/nginx/html
      - ./nginx/local.conf:/etc/nginx/conf.d/default.conf
    depends_on:
      - promiselink-api
    restart: unless-stopped
```

### 7.3 基础版 vs 专业版 Docker对比

| 服务 | 基础版 | 专业版 | 说明 |
|------|--------|--------|------|
| `promiselink-api` | ✅ | ✅ | FastAPI业务服务（专业版内含relay_client后台Task） |
| `promiselink-web` | ✅ | ✅ | Nginx托管H5前端 |
| 环境变量 `APP_EDITION` | `basic` | `pro` | 版本切换 |
| 环境变量 `RELAY_GATEWAY_URL` | 无 | `wss://gw.promiselink.ai/relay` | 设置即启用relay_client |
| 环境变量 `RELAY_USER_TOKEN` | 无 | JWT签名token | 用户身份凭证 |
| 环境变量 `AI_MODE` | `local` | `relay` | AI调用模式 |
| 环境变量 `LLM_API_KEY` | 用户自填 | 无（网关代理） | API Key存储位置 |
| PostgreSQL | ❌ | ❌ (用户侧) | 用户侧仍用SQLite |
| Redis | ❌ | ❌ (用户侧) | 用户侧不需要 |

> **关键设计**: 专业版用户侧**不新增独立容器**，relay_client作为FastAPI进程内模块运行，共享同一容器资源，零额外部署开销。PG+Redis仅在**网关侧**使用。

### 7.4 网关高可用与降级

| 场景 | 降级策略 | 用户感知 |
|------|----------|----------|
| 网关重启 | relay_client自动重连（指数退避） | 短暂AI调用失败，自动恢复 |
| 网关宕机 | 本地Docker降级为只读模式 | 基础功能可用，AI功能不可用 |
| LLM API限流 | Key池自动切换到备用Key | 用户无感知 |
| 所有LLM Key耗尽 | 返回503 + 降级提示 | 提示"AI服务暂时不可用" |
| 用户PC离线 | 网关返回503给小程序 | 提示"本地服务未连接" |
| 用户额度用尽 | 网关拒绝AI调用 | 提示"本月AI额度已用完" |

---

## 8. 配置项汇总

### 8.1 专业版新增配置项

```python
# config.py 专业版扩展配置 (在现有Settings基础上新增)

class Settings(BaseSettings):
    # ... 现有配置 ...

    # ── 专业版: 网关中继配置 ──
    relay_gateway_url: str = Field(default="", description="网关WSS地址，设置即启用relay_client")
    relay_user_token: str = Field(default="", description="网关JWT令牌")
    relay_reconnect_interval: int = 1  # 初始重连间隔(秒)
    relay_reconnect_max: int = 30     # 最大重连间隔(秒)
    relay_heartbeat_interval: int = 30  # 心跳间隔(秒)
    ai_mode: str = "local"            # local / relay

    # ── 专业版: 许可验证 ──
    pro_license_key: str = Field(default="", description="专业版许可证密钥")

    # ── 专业版: 媒体服务 (已存在) ──
    asr_provider: str = "moka_ai"     # moka_ai / local_whisper / aliyun
    tts_provider: str = "moka_ai"     # moka_ai / edge_tts / wechat / aliyun
    ocr_provider: str = "moka_ai"     # moka_ai / paddleocr / tencent
    media_max_audio_size_mb: int = 25
    media_max_image_size_mb: int = 10

    # ── 专业版: 邮件同步 ──
    email_imap_host: str = ""
    email_imap_port: int = 993
    email_imap_ssl: bool = True
    email_username: str = ""
    email_password: str = ""          # 应用专用密码
    email_sync_interval: int = 300    # 同步间隔(秒)，0=手动

    # ── 专业版: 隐私数据管理 ──
    pii_encryption_key: str = Field(default="", description="PII加密密钥，独立于secret_key")
    privacy_audit_log_enabled: bool = True
    privacy_mask_display: bool = True # 展示层脱敏
```

### 8.2 环境变量映射

```bash
# .env.pro.example (专业版环境变量示例)

# 版本控制
APP_EDITION=pro

# 网关中继
RELAY_GATEWAY_URL=wss://gw.promiselink.ai/relay
RELAY_USER_TOKEN=eyJhbGciOiJIUzI1NiIs...
AI_MODE=relay

# 许可证
PRO_LICENSE_KEY=PL-PRO-xxxx-xxxx

# 媒体服务 (专业版走网关代理，无需单独配置Key)
ASR_PROVIDER=moka_ai
TTS_PROVIDER=moka_ai
OCR_PROVIDER=moka_ai

# 邮件同步 (可选)
EMAIL_IMAP_HOST=imap.qq.com
EMAIL_IMAP_PORT=993
EMAIL_IMAP_SSL=true
EMAIL_USERNAME=user@qq.com
EMAIL_PASSWORD=app-specific-password
EMAIL_SYNC_INTERVAL=300

# 隐私数据
PII_ENCRYPTION_KEY=your-independent-pii-key
PRIVACY_AUDIT_LOG_ENABLED=true
PRIVACY_MASK_DISPLAY=true

# 注意: 专业版不需要 LLM_API_KEY (走网关代理)
# 注意: 专业版不需要 DEEPSEEK_API_KEY (走网关代理)
```

---

## 9. 技术选型决策汇总

| 模块 | 首选方案 | 降级方案 | 选型理由 | 实现状态 |
|------|----------|----------|----------|----------|
| **ASR** | Moka AI Whisper | 本地Whisper | OpenAI兼容、中文效果好、与LLM统一认证 | ✅ 已实现 |
| **NLU** | LLM意图分类 | 规则引擎 | 灵活、支持复杂意图、零规则维护 | ✅ 已实现 |
| **TTS** | 微信同声传译(前端) + Moka AI TTS(后端) | Edge-TTS | 前端免费原生、后端统一认证 | ✅ 已实现 |
| **OCR** | Moka AI Vision | PaddleOCR | 结构化提取、语义理解、统一认证 | ✅ 已实现 |
| **邮件** | Python imaplib | - | 标准库、零依赖、SSL/TLS | ✅ 已实现 |
| **微信转发** | 规则解析(正则) | LLM增强 | 零LLM依赖、毫秒级、可预测 | ✅ 已实现 |
| **CSV导入** | Python csv | pandas(大文件) | 标准库、轻量 | ✅ 已实现 |
| **PII加密** | AES-256-GCM | - | 工业标准、认证加密 | ✅ 已实现 |
| **LLM** | DeepSeek (经网关) | Moka AI | 中文能力强、成本低 | 网关待实现 |
| **网关** | FastAPI + WebSocket | - | 与业务服务统一技术栈 | 待实现 |
| **网关DB** | PostgreSQL + Redis | - | 多用户并发、连接映射缓存 | 待实现 |

---

## 10. 附录

### 10.1 已实现代码清单

| 模块 | 文件路径 | 说明 |
|------|----------|------|
| 配置 | `src/promiselink/config.py` | APP_EDITION + 媒体服务配置 |
| 路由注册 | `src/promiselink/main.py` | 条件注册Pro路由 |
| ASR | `src/promiselink/services/asr_service.py` | Moka AI Whisper + 本地降级 |
| TTS | `src/promiselink/services/tts_service.py` | Moka AI TTS |
| OCR | `src/promiselink/services/ocr_service.py` | Moka AI Vision |
| NLU | `src/promiselink/services/nlu_intent_classifier.py` | LLM意图分类 |
| 语音查询 | `src/promiselink/services/voice_query_service.py` | 语音查询响应 |
| NLG | `src/promiselink/services/nlg_service.py` | 自然语言生成 |
| 邮件 | `src/promiselink/services/email_adapter.py` | IMAP邮件拉取 |
| 微信转发 | `src/promiselink/services/wechat_forward_adapter.py` | 正则解析 |
| PII加密 | `src/promiselink/core/crypto.py` | AES-256-GCM |
| 媒体API | `src/promiselink/api/v1/media.py` | ASR/TTS/OCR端点 |
| 语音API | `src/promiselink/api/v1/voice.py` | 语音会话端点 |
| 语音查询API | `src/promiselink/api/v1/voice_query.py` | 语音查询端点 |
| 邮件API | `src/promiselink/api/v1/email_sync.py` | 邮件同步端点 |
| 微信API | `src/promiselink/api/v1/wechat_forward.py` | 微信转发端点 |
| CSV API | `src/promiselink/api/v1/import_csv.py` | CSV导入端点 |
| 隐私API | `src/promiselink/api/v1/privacy.py` | GDPR端点 |

### 10.2 待实现代码清单

| 模块 | 文件路径(计划) | 说明 |
|------|----------------|------|
| relay_client | `src/promiselink/services/relay_client.py` | 网关中继客户端(嵌入式Task) |
| 网关服务 | `gateway/` (独立项目) | 云端AI网关 |
| 网关中继路由 | `gateway/relay_router.py` | WebSocket连接管理+请求转发 |
| 网关AI代理 | `gateway/ai_proxy.py` | LLM/ASR/TTS/OCR代理 |
| 网关Key池 | `gateway/api_key_pool.py` | API Key轮询+限流+熔断 |
| 网关许可验证 | `gateway/license_service.py` | PRO_LICENSE_KEY验证 |
| 网关计费 | `gateway/billing_service.py` | Token计数+用量限制 |
| 网关数据模型 | `gateway/models.py` | User/License/Usage模型 |

### 10.3 参考文档

- `docs/architecture/PromiseLink_技术设计_v1.md` §8.7 — 网关中继架构协议层设计
- `docs/architecture/edition_architecture.md` — 基础版/专业版版本对比和安全模型
- `docs/spec/PRD_v1.md` §1.5 — 三层产品分层架构
- `docs/基础版与专业版开发计划_v1.0.md` — 高层开发计划
- `docs/planning/Pro_Edition_Implementation_Plan.md` — 分阶段详细实现计划(姊妹篇)
