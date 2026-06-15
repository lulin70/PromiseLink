#!/usr/bin/env python3
"""
PromiseLink 提取结果详细报告
逐个Event提交，等待Pipeline完成，展示每个Event提取的实体/关联/Todo
用于排查"李总"实体提取丢失问题
"""
import httpx
import uuid
import time
import json
import sys
import os

BASE = "http://localhost:8001/api/v1"
SECRET = os.environ.get("POC_SECRET", "promiselink2024")

# 测试用的交流记录（包含"李总"）
TEST_EVENTS = [
    {
        "event_type": "meeting",
        "raw_text": "与李总开会讨论项目方案。李总是华创科技的CEO，他关心项目交付时间，希望7月底前上线。我承诺本周五前发送技术方案给他。李总答应安排技术团队下周做评审。",
        "source": "manual",
        "title": "与李总讨论项目方案",
    },
    {
        "event_type": "meeting",
        "raw_text": "今天和陈宇鑫讨论了数字名片对接方案。陈宇鑫是数字名片公司的技术负责人，他表示可以提供API接口，包含姓名、公司、职位、联系方式等字段。我承诺本周五之前评估技术可行性并给反馈。陈宇鑫关心我们系统的数据安全合规性。",
        "source": "manual",
        "title": "与陈宇鑫讨论数字名片对接",
    },
    {
        "event_type": "call",
        "raw_text": "给王总打电话确认合作意向。王总是盛达集团的采购总监，他说正在寻找新的供应商，对我们的方案感兴趣。我答应明天发详细报价单给他。王总担心售后服务响应速度。",
        "source": "manual",
        "title": "与王总电话确认合作意向",
    },
]


def wait_for_pipeline(client, headers, event_id, max_wait=60):
    """等待Pipeline处理完成，返回event状态"""
    for i in range(max_wait // 3):
        time.sleep(3)
        r = client.get(f"{BASE}/events/{event_id}", headers=headers)
        if r.status_code == 200:
            event = r.json()
            status = event.get("status", "?")
            if status in ("completed", "failed"):
                return event
        else:
            print(f"    [WARN] GET /events/{event_id[:8]} 返回 {r.status_code}")
    return None


def get_entities_for_event(client, headers, event_id):
    """获取某个event关联的实体"""
    r = client.get(f"{BASE}/entities?source_event_id={event_id}", headers=headers)
    if r.status_code == 200:
        return r.json().get("items", [])
    # fallback: 获取全部实体再过滤
    r = client.get(f"{BASE}/entities", headers=headers)
    if r.status_code == 200:
        return [e for e in r.json().get("items", []) if e.get("source_event_id") == event_id]
    return []


def get_todos_for_event(client, headers, event_id):
    """获取某个event关联的Todo"""
    r = client.get(f"{BASE}/todos?source_event_id={event_id}", headers=headers)
    if r.status_code == 200:
        return r.json().get("items", [])
    # fallback
    r = client.get(f"{BASE}/todos", headers=headers)
    if r.status_code == 200:
        return [t for t in r.json().get("items", []) if t.get("source_event_id") == event_id]
    return []


def get_associations(client, headers, user_id):
    """获取所有关联"""
    r = client.get(f"{BASE}/associations", headers=headers)
    if r.status_code == 200:
        return r.json().get("items", r.json() if isinstance(r.json(), list) else [])
    return []


def format_entity(e):
    """格式化实体信息"""
    name = e.get("name", "?")
    etype = e.get("entity_type", "?")
    props = e.get("properties", {})
    basic = props.get("basic", {}) if isinstance(props, dict) else {}
    company = basic.get("company", "") if isinstance(basic, dict) else ""
    title = basic.get("title", "") if isinstance(basic, dict) else ""
    concern = props.get("concern", []) if isinstance(props, dict) else []
    capability = props.get("capability", []) if isinstance(props, dict) else []

    lines = [f"    [{etype}] {name}"]
    if company:
        lines.append(f"      公司: {company}")
    if title:
        lines.append(f"      职位: {title}")
    if concern:
        for c in concern:
            if isinstance(c, dict):
                lines.append(f"      关注: {c.get('category', '')} - {c.get('detail', '')}")
            else:
                lines.append(f"      关注: {c}")
    if capability:
        for c in capability:
            if isinstance(c, dict):
                lines.append(f"      能力: {c.get('category', '')} - {c.get('detail', '')}")
            else:
                lines.append(f"      能力: {c}")
    return "\n".join(lines)


def format_todo(t):
    """格式化Todo信息"""
    ttype = t.get("todo_type", "?")
    title = t.get("title", "?")
    priority = t.get("priority", "?")
    status = t.get("status", "?")
    requires_conf = t.get("requires_confirmation", False)
    conf_mark = " [需确认]" if requires_conf else ""
    return f"    [{ttype}] {title} (优先级:{priority}, 状态:{status}){conf_mark}"


def format_association(a):
    """格式化关联信息"""
    atype = a.get("association_type", "?")
    src = a.get("source_entity_id", "?")[:8]
    tgt = a.get("target_entity_id", "?")[:8]
    props = a.get("properties", {})
    evidence = props.get("evidence", {}) if isinstance(props, dict) else {}
    detail = ""
    if atype == "same_city":
        detail = f"同城: {evidence.get('city', '?')}"
    elif atype == "industry_chain":
        detail = f"产业链: {evidence.get('relation', '?')}"
    elif atype == "topic_overlap":
        topics = evidence.get("shared_topics", [])
        detail = f"同领域: {', '.join(topics[:3]) if topics else '?'}"
    elif atype == "supply_demand":
        detail = f"供需匹配"
    return f"    [{atype}] {src}... → {tgt}... {detail}"


def main():
    print("=" * 70)
    print("  PromiseLink 提取结果详细报告")
    print("  排查：每个Event后找到了什么实体、关联、Todo")
    print("=" * 70)

    with httpx.Client(timeout=30) as client:
        # 登录
        uid = str(uuid.uuid4())
        fake_ip = "10.0.88.1"
        r = client.post(
            f"{BASE}/auth/login",
            json={"user_id": uid, "poc_secret": SECRET},
            headers={"X-Forwarded-For": fake_ip},
        )
        if r.status_code != 200:
            print(f"  登录失败: {r.status_code} {r.text}")
            sys.exit(1)
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"\n  登录成功 user_id={uid[:8]}...")

        # 逐个提交Event，等待Pipeline完成，查看结果
        all_results = []

        for idx, event_data in enumerate(TEST_EVENTS):
            print(f"\n{'=' * 70}")
            print(f"  Event #{idx + 1}: {event_data['title']}")
            print(f"  类型: {event_data['event_type']}")
            print(f"  内容: {event_data['raw_text'][:60]}...")
            print(f"{'=' * 70}")

            # 提交Event
            r = client.post(f"{BASE}/events", headers=headers, json=event_data)
            if r.status_code not in (200, 201):
                print(f"  [ERROR] 创建Event失败: {r.status_code} {r.text[:200]}")
                continue

            event = r.json()
            event_id = event.get("id", "")
            print(f"  创建成功 event_id={event_id[:8]}... status={event.get('status', '?')}")

            # 等待Pipeline处理
            print(f"  等待Pipeline处理...")
            result_event = wait_for_pipeline(client, headers, event_id, max_wait=90)

            if result_event is None:
                print(f"  [ERROR] Pipeline超时未完成!")
                continue

            status = result_event.get("status", "?")
            error = result_event.get("error", "")
            print(f"  Pipeline状态: {status}")
            if error:
                print(f"  错误信息: {error[:200]}")

            # 查看提取的实体
            entities = get_entities_for_event(client, headers, event_id)
            print(f"\n  --- 提取的实体 ({len(entities)} 个) ---")
            if entities:
                for e in entities:
                    print(format_entity(e))
            else:
                print("    (无实体提取)")

            # 查看生成的Todo
            todos = get_todos_for_event(client, headers, event_id)
            print(f"\n  --- 生成的Todo ({len(todos)} 个) ---")
            if todos:
                for t in todos:
                    print(format_todo(t))
            else:
                print("    (无Todo生成)")

            # 查看关联
            associations = get_associations(client, headers, uid)
            print(f"\n  --- 当前所有关联 ({len(associations)} 个) ---")
            if associations:
                for a in associations:
                    print(format_association(a))
            else:
                print("    (暂无关联)")

            all_results.append({
                "event_id": event_id,
                "title": event_data["title"],
                "status": status,
                "entities_count": len(entities),
                "todos_count": len(todos),
                "entities": entities,
                "todos": todos,
            })

        # 最终汇总
        print(f"\n{'=' * 70}")
        print(f"  最终汇总")
        print(f"{'=' * 70}")

        # 全部实体
        r = client.get(f"{BASE}/entities", headers=headers)
        all_entities = r.json().get("items", [])
        print(f"\n  全部联系人 ({len(all_entities)} 个):")
        for e in all_entities:
            print(format_entity(e))

        # 全部Todo
        r = client.get(f"{BASE}/todos", headers=headers)
        all_todos = r.json().get("items", [])
        print(f"\n  全部Todo ({len(all_todos)} 个):")
        for t in all_todos:
            print(format_todo(t))

        # 全部关联
        associations = get_associations(client, headers, uid)
        print(f"\n  全部关联 ({len(associations)} 个):")
        for a in associations:
            print(format_association(a))

        # 逐Event汇总表
        print(f"\n  +{'─' * 60}+")
        print(f"  | {'Event':20s} | {'状态':10s} | {'实体':4s} | {'Todo':4s} |")
        print(f"  +{'─' * 60}+")
        for r in all_results:
            print(f"  | {r['title'][:20]:20s} | {r['status']:10s} | {r['entities_count']:4d} | {r['todos_count']:4d} |")
        print(f"  +{'─' * 60}+")

        # 关键验证：李总是否被提取
        li_found = any("李总" in e.get("name", "") for e in all_entities)
        print(f"\n  关键验证: 李总实体 {'已找到' if li_found else '未找到!!!'}")

        # 判定
        print(f"\n{'=' * 70}")
        if li_found and len(all_entities) >= 2 and len(all_todos) >= 3:
            print("  RESULT: PASS - 实体提取和Todo生成正常!")
        elif li_found:
            print("  RESULT: PARTIAL - 李总已提取，但其他数据不完整")
        else:
            print("  RESULT: FAIL - 李总实体提取失败，需排查!")
        print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
