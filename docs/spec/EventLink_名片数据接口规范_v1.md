# EventLink 名片数据接口规范 v1.2

**日期**：2026-06-03
**状态**：草案（待无界团队确认字段映射）
**关联**：PRD v4.0 §3.1 F-01 / 技术设计 v2.2 §4.1 card_save管线

***

## 1. 概述

本文档定义了 EventLink 的 `card_save` 管线接收名片数据的 JSON Schema。

### 数据流方向

```
数据流入（名片→EventLink）：
无界小程序（或其他名片源）──POST /api/v1/events──→ EventLink
                                                   │
                                                   └─ event_type: "card_save"
                                                      source: "iamhere" | "manual"
                                                      raw_text: JSON字符串（本Schema定义的格式）

数据查询（小程序←EventLink）：
无界小程序 ──GET /api/v1/mini/entity/{id}/events──→ EventLink
                                                    │
                                                    └─ 返回该实体的交流记录概要（脱敏）
                                                       通过 person_id（wujie_person_id）关联查询
```

**核心原则**：

- 名片源只负责提供结构化数据，不负责AI推理
- EventLink负责从数据中提取实体、推断关联、生成Todo
- 名片数据单向流入：名片源 → EventLink
- 交流历史概要按需查询：小程序 ← EventLink（通过person_id关联，仅脱敏概要，非原始数据）

***

## 2. Event 接口层（已有API）

名片数据作为 `POST /api/v1/events` 的请求体传入，`event_type` 固定为 `card_save`：

```json
{
  "event_type": "card_save",
  "source": "wujie",
  "title": "与张伟交换名片",
  "timestamp": "2026-06-03T14:30:00+08:00",
  "raw_text": "{ ... 名片JSON字符串 ... }",
  "metadata": {
    "source_app": "坐忘无界",
    "source_version": "1.0.0",
    "scan_method": "qrcode",
    "person_id": "wujie_person_id"
  }
}
```

> **注意**：`raw_text` 字段存放的是名片 JSON **字符串**（需 `JSON.stringify`），不是嵌套对象。这是为了和 meeting/call/manual 管线保持一致的文本输入接口。名片 JSON 解析准确率验收标准：>95%（PRD AC-01）。

***

## 3. 名片 JSON Schema（raw\_text 内部格式）

### 3.1 完整 Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "EventLink Business Card",
  "description": "EventLink card_save 管线的名片数据输入格式",
  "type": "object",
  "required": ["person"],
  "additionalProperties": true,

  "properties": {
    "person": {
      "type": "object",
      "description": "名片主体：联系人信息",
      "required": ["name"],
      "additionalProperties": true,
      "properties": {
        "name": {
          "type": "string",
          "description": "姓名（必填，唯一必填字段）",
          "minLength": 1,
          "maxLength": 100,
          "examples": ["张伟", "David Chen"]
        },
        "name_en": {
          "type": ["string", "null"],
          "description": "英文名/拼音（用于别名匹配）",
          "maxLength": 100,
          "examples": ["David Chen", "ZHANG Wei"]
        },
        "title": {
          "type": ["string", "null"],
          "description": "职位",
          "maxLength": 100,
          "examples": ["副总裁", "Senior Product Manager"]
        },
        "company": {
          "type": ["string", "null"],
          "description": "公司/组织名",
          "maxLength": 200,
          "examples": ["华为技术有限公司", "Tencent"]
        },
        "company_short": {
          "type": ["string", "null"],
          "description": "公司简称/别名（用于归一匹配）",
          "maxLength": 50,
          "examples": ["华为", "腾讯"]
        },
        "department": {
          "type": ["string", "null"],
          "description": "部门",
          "maxLength": 100,
          "examples": ["云业务部", "AI Lab"]
        },
        "avatar_url": {
          "type": ["string", "null"],
          "format": "uri",
          "description": "头像URL（仅存URL，不存图片）"
        }
      }
    },

    "contact": {
      "type": ["object", "null"],
      "description": "联系方式（全部可选，按使用频率排序）",
      "additionalProperties": true,
      "properties": {
        "mobile": {
          "type": ["string", "null"],
          "description": "手机号（含国际区号）",
          "pattern": "^\\+?\\d{7,15}$",
          "examples": ["+86 13800138000", "+1 4155551234"]
        },
        "email": {
          "type": ["string", "null"],
          "format": "email",
          "description": "工作邮箱",
          "examples": ["zhangwei@huawei.com"]
        },
        "wechat": {
          "type": ["string", "null"],
          "description": "微信号",
          "maxLength": 50,
          "examples": ["zhangwei_huawei"]
        },
        "phone_work": {
          "type": ["string", "null"],
          "description": "办公电话",
          "maxLength": 30
        },
        "linkedin": {
          "type": ["string", "null"],
          "description": "LinkedIn主页URL",
          "format": "url"
        }
      }
    },

    "location": {
      "type": ["object", "null"],
      "description": "地理位置信息（用于same_city关联推断）",
      "additionalProperties": true,
      "properties": {
        "city": {
          "type": ["string", "null"],
          "description": "城市（优先使用中文名）",
          "maxLength": 50,
          "examples": ["深圳", "上海", "San Francisco"]
        },
        "province": {
          "type": ["string", "null"],
          "description": "省份/州",
          "maxLength": 50,
          "examples": ["广东省", "California"]
        },
        "country": {
          "type": ["string", "null"],
          "description": "国家",
          "maxLength": 50,
          "examples": ["中国", "USA"],
          "default": "中国"
        },
        "address": {
          "type": ["string", "null"],
          "description": "详细地址",
          "maxLength": 300,
          "examples": ["深圳市龙岗区坂田华为基地"]
        }
      }
    },

    "industry": {
      "type": ["object", "null"],
      "description": "行业信息（用于行业一致性匹配和领域分类）",
      "additionalProperties": true,
      "properties": {
        "category": {
          "type": ["string", "null"],
          "description": "行业大类（对应PRD领域分类L1，如D01-D18）",
          "maxLength": 50,
          "examples": ["信息技术", "金融", "制造业"]
        },
        "sub_category": {
          "type": ["string", "null"],
          "description": "行业子类",
          "maxLength": 50,
          "examples": ["云计算", "风险投资", "智能硬件"]
        },
        "keywords": {
          "type": "array",
          "description": "业务关键词（用于商机匹配关键词重叠维度）",
          "items": {
            "type": "string",
            "maxLength": 30
          },
          "maxItems": 10,
          "examples": [["AI", "云计算", "数字化转型"]]
        }
      }
    },

    "business": {
      "type": ["object", "null"],
      "description": "商务信息（Phase1可选，Phase2推荐）",
      "additionalProperties": true,
      "properties": {
        "core_resource": {
          "type": ["string", "null"],
          "description": "核心资源/能力概述（李总版Resource简化字段）",
          "maxLength": 200,
          "examples": ["华南地区工厂资源丰富", "可提供企业级云服务"]
        },
        "service_scope": {
          "type": ["string", "null"],
          "description": "服务/产品范围",
          "maxLength": 200,
          "examples": ["办公设备租赁、智能办公解决方案"]
        },
        "client_type": {
          "type": ["string", "null"],
          "description": "客户类型",
          "maxLength": 100,
          "examples": ["企业客户（中大型）", "初创公司"]
        }
      }
    },

    "interaction_context": {
      "type": ["object", "null"],
      "description": "首次交互场景（EventLink利他闭环核心字段）",
      "additionalProperties": true,
      "properties": {
        "met_via": {
          "type": ["string", "null"],
          "description": "认识途径",
          "enum": ["conference", "referral", "cold_outreach", "social", "partner", "other", null],
          "examples": ["conference"]
        },
        "met_via_detail": {
          "type": ["string", "null"],
          "description": "认识途径补充说明",
          "maxLength": 200,
          "examples": ["2026深圳AI峰会", "许总介绍"]
        },
        "their_concern": {
          "type": ["string", "null"],
          "description": "对方正在关心的事（利他闭环起点）",
          "maxLength": 500,
          "examples": ["正在找AI落地方案", "公司数字化转型中"]
        },
        "my_promise": {
          "type": ["string", "null"],
          "description": "我答应对方的事（承诺追踪起点）",
          "maxLength": 500,
          "examples": ["下周发一份案例给他", "帮忙对接供应商"]
        },
        "follow_up_hint": {
          "type": ["string", "null"],
          "description": "下次联系的抓手/理由",
          "maxLength": 200,
          "examples": ["说好3月底前给反馈", "他提到下周来深圳"]
        }
      }
    },

    "social_links": {
      "type": ["array", "null"],
      "description": "社交链接（名片上的其他链接）",
      "items": {
        "type": "object",
        "required": ["url"],
        "properties": {
          "platform": {
            "type": "string",
            "description": "平台名称",
            "examples": ["github", "twitter", "website", "blog"]
          },
          "url": {
            "type": "string",
            "format": "uri"
          }
        }
      },
      "maxItems": 5
    },

    "custom_fields": {
      "type": ["object", "null"],
      "description": "自定义扩展字段（名片源可自由添加，EventLink透传到Entity.properties）",
      "additionalProperties": true
    },

    "meta": {
      "type": ["object", "null"],
      "description": "名片元数据",
      "properties": {
        "card_id": {
          "type": ["string", "null"],
          "description": "名片源方的唯一ID（用于去重和溯源）",
          "maxLength": 100
        },
        "card_type": {
          "type": ["string", "null"],
          "description": "名片类型",
          "enum": ["basic", "agent", "agent_digital_human", "imported", "manual", null]
        },
        "created_at": {
          "type": ["string", "null"],
          "format": "date-time",
          "description": "名片创建时间（名片源方时间）"
        },
        "verified": {
          "type": ["boolean", "null"],
          "description": "是否经名片源方验证",
          "default": false
        },
        "language": {
          "type": ["string", "null"],
          "description": "名片主要语言",
          "enum": ["zh-CN", "zh-TW", "en", "ja", "ko", null],
          "default": "zh-CN"
        }
      }
    }
  }
}
```

### 3.2 字段分类与阶段映射

| 字段组                  | PoC   | Phase1 | Phase2 | 说明                       |
| -------------------- | ----- | ------ | ------ | ------------------------ |
| person（姓名/职位/公司）     | ✅ 必填  | ✅      | ✅      | 名片核心，零门槛                 |
| contact（联系方式）        | ✅ 推荐  | ✅      | ✅      | 归一关键线索（手机/邮箱精确匹配）        |
| location（城市）         | ✅ 推荐  | ✅推荐    | ✅推荐    | same\_city关联推断           |
| industry（行业/关键词）     | ⚠️ 可选 | ✅ 推荐   | ✅推荐    | 商机匹配核心维度                 |
| business（资源/服务）      | ❌ 不填  | ⚠️ 可选  | ✅ 推荐   | Phase2资源独立实体后必填          |
| interaction\_context | ✅ 推荐  | ✅推荐    | ✅推荐    | **利他闭环核心**——对方关心什么/我答应什么 |
| social\_links        | ❌ 不填  | ⚠️ 可选  | ✅      | 非核心                      |
| custom\_fields       | ✅ 透传  | ✅ 透传   | ✅ 透传   | 扩展用，不丢数据                 |
| meta                 | ✅ 推荐  | ✅      | ✅      | person\_id用于去重           |

***

## 4. 示例数据

### 4.1 最小有效名片（PoC冷启动）

```json
{
  "person": {
    "name": "张伟"
  }
}
```

> 只有名字也能进系统。EventLink会在后续交互中渐进填充其他字段。

### 4.2 标准名片（会议场景交换）

```json
{
  "person": {
    "name": "张伟",
    "name_en": "David Zhang",
    "title": "副总裁",
    "company": "华为技术有限公司",
    "company_short": "华为",
    "department": "云业务部"
  },
  "contact": {
    "mobile": "+86 13800138000",
    "email": "zhangwei@huawei.com",
    "wechat": "zhangwei_hw"
  },
  "location": {
    "city": "深圳",
    "province": "广东省",
    "country": "中国",
    "address": "龙岗区坂田华为基地"
  },
  "industry": {
    "category": "信息技术",
    "sub_category": "云计算",
    "keywords": ["AI", "云计算", "数字化转型"]
  },
  "interaction_context": {
    "met_via": "conference",
    "met_via_detail": "2026深圳AI峰会",
    "their_concern": "正在找AI落地到制造业的方案",
    "my_promise": "下周发一份制造业AI案例给他",
    "follow_up_hint": "说好3月底前给反馈"
  },
  "meta": {
    "card_id": "wujie_card_abc123",
    "card_type": "basic",
    "created_at": "2026-06-03T14:30:00+08:00",
    "language": "zh-CN"
  }
}
```

### 4.3 许总场景（语音录入+利他闭环）

```json
{
  "person": {
    "name": "王建军",
    "title": "总经理",
    "company": "中建南方装饰"
  },
  "contact": {
    "mobile": "+86 13900139000",
    "wechat": "wjj_zjn"
  },
  "location": {
    "city": "深圳"
  },
  "interaction_context": {
    "met_via": "referral",
    "met_via_detail": "许总介绍",
    "their_concern": "办公室要装修，想找个靠谱的",
    "my_promise": "帮他在我认识的装修供应商里推荐两家",
    "follow_up_hint": "他说这周内要定"
  },
  "meta": {
    "card_type": "manual",
    "language": "zh-CN"
  }
}
```

### 4.4 无界API批量导入（Phase1）

```json
{
  "person": {
    "name": "李明",
    "title": "CTO",
    "company": "某科技公司",
    "company_short": "某科技"
  },
  "contact": {
    "mobile": "+86 13700137000",
    "email": "liming@mokeji.com"
  },
  "location": {
    "city": "北京",
    "province": "北京市"
  },
  "industry": {
    "category": "信息技术",
    "keywords": ["SaaS", "企业服务"]
  },
  "business": {
    "core_resource": "企业级SaaS解决方案",
    "service_scope": "OA/CRM/ERP一体化",
    "client_type": "中大型企业"
  },
  "meta": {
    "card_id": "wujie_batch_202606_001",
    "card_type": "imported",
    "verified": true,
    "language": "zh-CN"
  }
}
```

***

## 5. 与 EventLink 内部数据模型的映射

名片JSON解析后，字段映射到 EventLink 内部实体：

| 名片字段                                  | EventLink 实体 | 目标字段                         | 映射规则                              |
| ------------------------------------- | ------------ | ---------------------------- | --------------------------------- |
| person.name                           | Entity       | name                         | 直接映射                              |
| person.name\_en                       | Entity       | aliases\[]                   | 追加到别名数组                           |
| person.title                          | Entity       | properties.title             | 直接映射                              |
| person.company                        | Entity       | properties.company           | 直接映射                              |
| person.company\_short                 | Entity       | aliases\[]                   | 追加到别名数组（公司别名）                     |
| person.department                     | Entity       | properties.department        | 直接映射                              |
| person.avatar\_url                    | Entity       | properties.avatar\_url       | 直接映射                              |
| contact.mobile                        | Entity       | properties.mobile            | 直接映射                              |
| contact.email                         | Entity       | properties.email             | 直接映射                              |
| contact.wechat                        | Entity       | properties.wechat            | 直接映射                              |
| location.city                         | Entity       | properties.city              | 直接映射，用于same\_city关联               |
| location.province                     | Entity       | properties.province          | 直接映射                              |
| location.country                      | Entity       | properties.country           | 直接映射                              |
| location.address                      | Entity       | properties.address           | 直接映射                              |
| industry.category                     | Entity       | properties.industry          | 直接映射                              |
| industry.sub\_category                | Entity       | properties.industry\_sub     | 直接映射                              |
| industry.keywords                     | Entity       | properties.keywords          | 直接映射，数组类型                         |
| business.core\_resource               | Entity       | properties.resource\_summary | Phase1：JSONB字段；Phase2：独立Resource表 |
| business.service\_scope               | Entity       | properties.service\_scope    | 直接映射到JSONB                        |
| business.client\_type                 | Entity       | properties.client\_type      | 直接映射到JSONB                        |
| interaction\_context.their\_concern   | Todo         | detail                       | 生成care类型Todo（雾蓝#A0B0C4）          |
| interaction\_context.my\_promise      | Todo         | detail                       | 生成promise类型Todo（雾绿#A0C4A8）        |
| interaction\_context.follow\_up\_hint | Todo         | suggestion                   | 生成followup类型Todo（雾金#C4C0A0）       |
| interaction\_context.met\_via         | Association  | evidence                     | 共现关联的evidence字段                   |
| meta.card\_id                         | Entity       | properties.source\_card\_id  | 去重依据                              |
| custom\_fields                        | Entity       | properties.custom            | 整体透传到JSONB                        |

### Organization 实体自动创建

当 `person.company` 非空时，card_save 管线自动创建 Organization 实体：

```python
Organization(
    name=card.person.company,
    entity_type="organization",
    aliases=[card.person.company_short] if card.person.company_short else [],
    properties={
        "industry": card.industry.category,
        "city": card.location.city,
        "source_card_ids": [card.meta.card_id] if card.meta.card_id else []
    }
)
```

***

## 6. 数据对接协议（与无界团队）

### 6.1 对接方式

| 阶段     | 方式          | 说明                           |
| ------ | ----------- | ---------------------------- |
| PoC    | 手动导出JSON    | 用户在无界导出名片JSON，在EventLink导入   |
| Phase1 | API拉取       | EventLink通过API从无界拉取授权用户的名片数据 |
| Phase2 | Webhook实时推送 | 名片创建/更新时，无界主动推送到EventLink    |

### 6.2 API接口规范（Phase1，待无界团队开发）

```
GET /api/v1/cards
Authorization: Bearer <user_access_token>
Query Parameters:
  - since: ISO8601 datetime（增量拉取起始时间）
  - limit: integer（单次拉取上限，默认50，最大200）
  - card_type: string（可选，过滤名片类型）

Response:
{
  "cards": [ { ... 名片JSON ... } ],
  "has_more": true,
  "next_cursor": "cursor_token_xyz"
}
```

### 6.3 EventLink 反向查询接口（小程序展示交流记录）

> **需求来源**：小程序在名片详情页需要展示"交流记录"，需按实体ID查询关联的Event概要。

**数据流**：

```
无界小程序 ──GET /api/v1/mini/entity/{id}/events──→ EventLink
                                                    │
                                                    └─ 返回脱敏后的Event概要清单
```

**接口规范**：

```
GET /api/v1/mini/entity/{entity_id}/events
Authorization: Bearer <mp_token>
Query Parameters:
  - limit: integer（单次返回上限，默认10，最大50）
  - offset: integer（分页偏移量，默认0）

Response:
{
  "entity_id": "ent_abc123",
  "entity_name": "张伟",
  "total_count": 23,
  "events": [
    {
      "event_id": "evt_xyz001",
      "event_type": "card_save",
      "title": "与张伟交换名片",
      "timestamp": "2026-06-03T14:30:00+08:00",
      "summary": "2026深圳AI峰会交换名片，对方关注AI落地制造业",
      "todo_count": 2
    },
    {
      "event_id": "evt_xyz002",
      "event_type": "meeting",
      "title": "与张伟午餐会",
      "timestamp": "2026-06-10T12:00:00+08:00",
      "summary": "讨论了云服务合作可能性",
      "todo_count": 1
    }
  ]
}
```

**脱敏规则**：

| 字段        | 脱敏方式     | 说明                           |
| --------- | -------- | ---------------------------- |
| summary   | AI生成的摘要  | 不暴露原始对话内容，仅返回结构化摘要           |
| raw\_text | **不返回**  | 原始文本可能含PII，仅EventLink内部使用    |
| metadata  | **不返回**  | 内部元数据不暴露给第三方                 |
| todo详情    | 仅返回count | 不暴露具体Todo内容，用户需进入EventLink查看 |

**边界约束**：

- 此接口仅返回**当前用户**与该实体的交流记录（user\_id隔离）
- 不返回其他用户与同一实体的交流记录
- 不返回实体的完整properties（含concern/promise/contribution等敏感字段）
- 小程序侧仅展示概要，详细内容需跳转EventLink H5页面

### 6.4 数据安全要求

| 要求   | 说明                                                       |
| ---- | -------------------------------------------------------- |
| 传输加密 | HTTPS/TLS 1.2+                                           |
| 数据方向 | 名片数据**单向流入**：无界 → EventLink；交流概要**按需查询**：小程序 ← EventLink |
| 用户授权 | 用户在无界侧主动授权导入，EventLink不主动拉取                              |
| 存储隔离 | 导入后数据存入EventLink本地数据库，与无界解耦                              |
| 字段过滤 | 仅导入名片基础字段，不导入无界的知识库/对话记录                                 |

***

## 7. Mock数据生成

PoC阶段使用mock数据，按本Schema生成。以下是mock数据的生成规则：

| 字段                   | 生成规则                             | 数量  |
| -------------------- | -------------------------------- | --- |
| person.name          | 中文姓名库（姓20+名40，随机组合）              | 20人 |
| person.title         | 职位库（VP/Director/Manager/CTO等10种） | 随机  |
| person.company       | 公司库（华为/腾讯/阿里等10家+虚构5家）           | 随机  |
| location.city        | 城市库（北上广深杭+5个二线）                  | 随机  |
| industry             | 领域库（IT/金融/制造业等8个L1类别）            | 随机  |
| interaction\_context | 50%概率填充（模拟语音录入场景）                | 随机  |
| contact              | 80%概率有手机，60%概率有邮箱                | 随机  |

***

## 8. 变更记录

| 版本   | 日期         | 变更                                                          |
| ---- | ---------- | ----------------------------------------------------------- |
| v1.0 | 2026-06-03 | 初版：定义名片JSON Schema，包含8个字段组                                  |
| v1.1 | 2026-06-03 | 新增§6.3反向查询接口（小程序展示交流记录），修正数据流为双向（名片单向流入+概要按需查询），明确脱敏规则和边界约束 |
| v1.2 | 2026-06-03 | 修正event_type统一为card_save（原card_scan/card_save混用）；修正数据流图（contact_history非event_type，改为反向查询接口说明）；修正§5映射表Todo类型标记为v4.0色值 |

