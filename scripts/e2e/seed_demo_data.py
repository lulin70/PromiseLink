#!/usr/bin/env python3
"""Seed PromiseLink with realistic demo data.

Based on real scenarios: 许总/陈宇欣 product discussions, 李总 feedback sessions,
and typical business relationship management use cases.

Usage:
  1. Start server: python -m uvicorn promiselink.main:app --port 8002
  2. Run seed: python scripts/e2e/seed_demo_data.py
"""

import asyncio
import sys

import httpx

BASE_URL = "http://localhost:8002/api/v1"
TIMEOUT = 120.0

# ── Realistic demo events based on actual project history ──

EVENTS = [
    # ── 许总（无界科技CEO）系列 ──
    {
        "event_type": "meeting",
        "timestamp": "2026-05-29T15:00:00+08:00",
        "raw_text": (
            "5月底简总介绍认识许总（许永亮），无界科技CEO，公司在深圳。"
            "许总对AI落地实践非常感兴趣，特别是AI记忆体产品。"
            "他提到他们正在做数字名片产品，希望集成AI能力。"
            "许总关心：1）数据安全性和隐私保护 2）部署成本 3）技术对接难度。"
            "我承诺下周发一份技术方案给他评估。"
        ),
    },
    {
        "event_type": "meeting",
        "timestamp": "2026-05-29T16:30:00+08:00",
        "raw_text": (
            "和许总正式会议，确认产品方向。许总提出三层架构思路："
            "1）基础层：名片识别+信息提取 2）增强层：关系图谱+智能提醒 3）高级层：AI主动推荐。"
            "许总认为应该先做基础层验证市场，再逐步升级。"
            "他关心交付时间，希望6月底前能看到PoC。"
            "我承诺6月15日前给出PoC演示。"
            "陈宇欣（许总的技术负责人）也参加了会议，他关心API接口设计和数据格式。"
        ),
    },
    {
        "event_type": "meeting",
        "timestamp": "2026-06-01T10:00:00+08:00",
        "raw_text": (
            "和许总、简讨论产品定位：侧重'人'还是'知识'？"
            "许总认为应该侧重'人'，因为商务关系的核心是人与人的信任和互动。"
            "简同意，说用户需要的是'我该关注谁、该帮谁、该跟谁跟进'，而不是知识库。"
            "最终共识：产品定位为'AI驱动的个人商务关系经营助手'，先成就关系再促成合作。"
            "许总承诺提供数字名片的用户反馈数据帮助我们优化。"
            "我承诺根据反馈调整产品方向。"
        ),
    },
    {
        "event_type": "meeting",
        "timestamp": "2026-06-02T14:00:00+08:00",
        "raw_text": (
            "和许总、陈宇欣讨论数字名片产品对接。"
            "陈宇欣介绍了他们的名片识别SDK，可以免费试用3个月。"
            "他关心：1）PromiseLink如何与名片小程序数据互通 2）用户身份如何关联 3）数据同步频率。"
            "我答应发API文档给陈宇欣，并安排技术对接会议。"
            "许总希望下周能看到数据互通的原型。"
            "陈宇欣说他们下周三下午有空做技术对接。"
        ),
    },
    # ── 李总（产品顾问）反馈系列 ──
    {
        "event_type": "meeting",
        "timestamp": "2026-06-01T11:00:00+08:00",
        "raw_text": (
            "李总看了PromiseLink的Demo后给出反馈："
            "1）定位太窄，不应该只做名片工具，应该升级为商务关系管理AI助手"
            "2）核心价值是'先成就关系再促成合作'，不是信息录入"
            "3）建议增加：承诺追踪、关注提醒、合作信号识别"
            "4）用户旅程应该是：互动→关注→承诺→帮助→反馈"
            "李总关心：产品能否真正帮用户经营关系，而不只是记录信息。"
            "我承诺根据反馈重新设计核心流程。"
        ),
    },
    {
        "event_type": "meeting",
        "timestamp": "2026-06-02T16:00:00+08:00",
        "raw_text": (
            "李总第二次反馈，提供了更详细的建议："
            "1）合作人员关键信息7板块30字段：基本信息、关注、承诺、贡献、资源、需求、互动频率"
            "2）16种角色分类：决策者、影响者、使用者、推荐人等"
            "3）会议标准知识卡片模板"
            "4）Todo类型应该分为：承诺、帮助、关注、跟进、合作信号、风险预警"
            "5）动态优先级评分：0.3×紧急性 + 0.35×重要性 + 0.2×依赖性 + 0.15×场景匹配"
            "李总承诺下周提供一份完整的客户需求分析报告。"
            "他关心我们能否在7月前完成基础版。"
        ),
    },
    # ── 典型商务场景 ──
    {
        "event_type": "meeting",
        "timestamp": "2026-06-03T15:00:00+08:00",
        "raw_text": (
            "今天下午3点和张伟总在望京SOHO的星巴克见面聊了新项目合作的事。"
            "张总说他们公司正在做数字化转型，需要一套完整的数据中台方案，预算大概在80-100万左右。"
            "他要求我们在下周五之前提交一份详细的技术方案和报价单。"
            "他还提到技术负责人是李明，让我直接联系李明对接技术细节。"
            "另外张总说如果这周能先出一个初步架构图就更好了，他下周二要给CEO汇报用。"
        ),
    },
    {
        "event_type": "call",
        "timestamp": "2026-06-04T09:30:00+08:00",
        "raw_text": (
            "刚才给王芳打了个电话，跟进上个月那个CRM系统项目。"
            "王芳说目前项目进度有点慢，客户那边催得比较急，问我们能不能加两个人手赶一下进度。"
            "她还提了一个新需求：客户希望增加一个移动端的审批流程模块，这个之前没在合同里。"
            "我跟她说新增模块需要重新评估工作量，可能要额外收费，她表示理解但希望尽快给出评估结果。"
            "我承诺明天中午12点前给她回复。"
        ),
    },
    {
        "event_type": "wechat_forward",
        "timestamp": "2026-06-04T11:00:00+08:00",
        "raw_text": (
            "微信上收到陈建国转发的一条消息，是他们的HR总监刘洋发的。"
            "刘洋说他们公司想找一家供应商做年度培训体系搭建，预算50万以内，"
            "主要需要领导力培训和新人入职培训两个方向。"
            "陈建国推荐了我们，说我们之前给他们做的培训效果不错。"
            "刘洋希望下周能安排一次线上会议聊聊具体需求。"
            "我回复说可以，让刘洋方便的时候联系我确定时间。"
        ),
    },
    {
        "event_type": "meeting",
        "timestamp": "2026-06-05T18:30:00+08:00",
        "raw_text": (
            "今天参加了一个行业交流饭局，经孙晓峰介绍认识了周婷。"
            "周婷是某大型互联网公司的采购总监，负责每年约2000万的软件采购。"
            "孙晓峰说周婷最近在找靠谱的数据分析工具供应商，正好我们的产品符合她的需求。"
            "周婷对产品演示很感兴趣，让我下周联系她的助理小吴安排时间。"
            "交换了名片，孙晓峰还提到周婷和他是大学同学，关系很铁。"
        ),
    },
    {
        "event_type": "manual",
        "timestamp": "2026-06-06T17:00:00+08:00",
        "raw_text": (
            "今天内部复盘会上的待办事项整理："
            "1. 周一前完成Q2季度报告的数据汇总"
            "2. 下周三之前更新产品路线图PPT，加入客户反馈的新功能点"
            "3. 这周内找赵磊确认API接口文档的交付时间，他说这周会给但还没发"
            "4. 记得提醒自己下周四下午2点参加产品评审会"
        ),
    },
    # ── 关系阶段：从陌生到熟悉 ──
    {
        "event_type": "meeting",
        "timestamp": "2026-04-15T10:00:00+08:00",
        "raw_text": (
            "在行业峰会上加了刘博士的微信，他是清华AI实验室的研究员，"
            "做自然语言处理方向。简单聊了几句，交换了名片。"
            "他说最近在研究企业知识图谱，可能和我们的产品有交集。"
        ),
    },
    {
        "event_type": "call",
        "timestamp": "2026-05-10T14:00:00+08:00",
        "raw_text": (
            "给刘博士打了个电话，约了下周去他实验室交流。"
            "他提到他们有一个知识图谱的demo，可以给我们看看。"
            "我承诺下周带产品Demo过去，互相交流。"
        ),
    },
    {
        "event_type": "meeting",
        "timestamp": "2026-05-20T09:30:00+08:00",
        "raw_text": (
            "去清华拜访了刘博士，看了他们的知识图谱demo，很有参考价值。"
            "刘博士对我们的关系图谱产品也很感兴趣，说可以合作研究。"
            "他关心数据隐私和学术发表的问题。"
            "我承诺回去整理一份合作方案，下周发给他。"
            "刘博士说他们6月底有一个学术会议，希望我们能在会上做个展示。"
        ),
    },
    # ── 沉睡人脉：很久没联系的人 ──
    {
        "event_type": "meeting",
        "timestamp": "2025-11-20T12:00:00+08:00",
        "raw_text": (
            "和老同学黄磊一起吃了午饭，他在一家上市公司做CTO。"
            "聊了各自近况，他说公司正在做AI转型，需要外部技术顾问。"
            "我答应回头发一份我们公司的介绍材料给他。"
            "黄磊关心技术落地的成本和周期。"
        ),
    },
    {
        "event_type": "wechat_forward",
        "timestamp": "2025-12-05T16:00:00+08:00",
        "raw_text": (
            "微信上给黄磊发了公司介绍材料，他说收到了，会转给技术VP看。"
            "他说下周安排一次线上会议聊聊。"
        ),
    },
    # ── 高考后问成绩的案例 ──
    {
        "event_type": "manual",
        "timestamp": "2026-06-07T08:00:00+08:00",
        "raw_text": (
            "记得高考是6月7-8号，马哥的儿子今年高考。"
            "等考完（6月9号之后）要主动问候一下，问孩子考得怎么样。"
            "马哥是老朋友了，去年帮我们介绍了两个客户，一直没好好感谢。"
            "趁高考这个时机，表达关心，顺便约个饭。"
        ),
    },
    {
        "event_type": "call",
        "timestamp": "2026-06-09T10:00:00+08:00",
        "raw_text": (
            "给马哥打了个电话，问孩子高考考得怎么样。"
            "马哥说孩子感觉还行，等6月25号出成绩。"
            "我说到时候再联系，如果考得好一起庆祝。"
            "马哥很感动，说没想到我还记得他孩子高考的事。"
            "我承诺出成绩那天再打电话祝贺。"
            "马哥提到他最近在帮一个朋友找AI解决方案，说可以推荐我们。"
        ),
    },
    # ── 沉睡人脉：前同事 ──
    {
        "event_type": "meeting",
        "timestamp": "2025-09-15T18:30:00+08:00",
        "raw_text": (
            "前同事杨帆约我吃饭，他现在在一家创业公司做产品总监。"
            "聊了各自的职业发展，他说公司刚拿到B轮融资，在扩团队。"
            "他问我有没有兴趣加入，我说现在做自己的项目，暂时不考虑。"
            "但他说他们需要AI方面的技术合作，我答应回头发一份合作方案。"
        ),
    },
    # ── 关系阶段：深度合作伙伴 ──
    {
        "event_type": "meeting",
        "timestamp": "2026-06-10T19:00:00+08:00",
        "raw_text": (
            "和许总、陈宇欣一起吃了晚饭，庆祝PoC演示成功。"
            "许总非常满意，当场决定推进正式合作。"
            "他承诺下周安排法务对接合同，目标7月1号前签约。"
            "陈宇欣说技术对接已经没问题了，下周可以开始联调。"
            "许总还介绍了他的另一个朋友何总，做智慧园区的，也有AI需求。"
            "何总下周想来我们公司看看。"
            "我承诺准备一份智慧园区的解决方案给何总。"
        ),
    },
]


async def seed():
    print("=" * 60)
    print("  PromiseLink 演示数据填充")
    print(f"  共 {len(EVENTS)} 条事件待录入")
    print("=" * 60)

    async with httpx.AsyncClient(base_url="http://localhost:8002", timeout=TIMEOUT) as c:
        # Login
        r = await c.post(f"{BASE_URL}/auth/login", json={
            "user_id": "poc-user",
            "poc_secret": "promiselink2026",
        })
        if r.status_code != 200:
            print(f"  登录失败: {r.status_code} {r.text}")
            sys.exit(1)
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("\n  登录成功")

        # Check existing data
        r = await c.get(f"{BASE_URL}/entities", headers=headers)
        existing = r.json()
        existing_count = len(existing) if isinstance(existing, list) else len(existing.get("items", []))
        if existing_count > 0:
            print(f"  当前已有 {existing_count} 个实体，将追加数据")

        # Seed events one by one (Pipeline needs sequential processing)
        success = 0
        failed = 0
        for i, event_data in enumerate(EVENTS):
            print(f"\n  [{i+1}/{len(EVENTS)}] 录入: {event_data['raw_text'][:50]}...")
            r = await c.post(f"{BASE_URL}/events", headers=headers, json={
                **event_data,
                "source": "manual",
            })
            if r.status_code in [200, 201]:
                event_id = r.json()["id"]
                print(f"  创建成功: {event_id[:8]}...")
                success += 1
            else:
                print(f"  创建失败: {r.status_code} {r.text[:100]}")
                failed += 1

            # Wait for pipeline between events (avoid overwhelming LLM API)
            if i < len(EVENTS) - 1:
                print("  等待Pipeline处理...")
                await asyncio.sleep(30)

        # Final wait for last event pipeline
        print("\n  等待最后一条事件Pipeline处理...")
        await asyncio.sleep(40)

        # Show results
        print("\n" + "=" * 60)
        print("  填充结果")
        print("=" * 60)

        r = await c.get(f"{BASE_URL}/entities", headers=headers)
        entities = r.json()
        entity_items = entities if isinstance(entities, list) else entities.get("items", [])
        print(f"\n  实体 ({len(entity_items)}个):")
        for e in entity_items:
            props = e.get("properties", {}) or {}
            concern = props.get("concern", "")
            capability = props.get("capability", "")
            info = []
            if concern:
                info.append(f"关注:{concern}" if isinstance(concern, str) else f"关注:{concern}")
            if capability:
                info.append(f"能力:{capability}" if isinstance(capability, str) else f"能力:{capability}")
            detail = " | ".join(info) if info else ""
            print(f"    - {e['name']} ({e.get('entity_type','?')}) {detail}")

        r = await c.get(f"{BASE_URL}/todos", headers=headers)
        todos = r.json()
        todo_items = todos if isinstance(todos, list) else todos.get("items", [])

        type_labels = {
            "promise": "承诺", "help": "帮助", "care": "关注",
            "followup": "跟进", "cooperation_signal": "合作信号", "risk": "风险",
        }
        by_type = {}
        for t in todo_items:
            by_type.setdefault(t.get("todo_type", "?"), []).append(t)

        print(f"\n  待办 ({len(todo_items)}条):")
        for tt, items in by_type.items():
            label = type_labels.get(tt, tt)
            print(f"    [{label}] ({len(items)}条)")
            for t in items[:3]:
                print(f"      - {t.get('title','?')[:60]}")
            if len(items) > 3:
                print(f"      ... 还有 {len(items)-3} 条")

        print(f"\n  录入: {success}成功 / {failed}失败")
        print(f"  实体: {len(entity_items)} | 待办: {len(todo_items)}")
        print("\n  浏览器访问 http://localhost:8002 查看完整数据")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(seed())
