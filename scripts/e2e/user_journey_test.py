#!/usr/bin/env python3
"""PromiseLink 用户旅程模拟测试"""
import asyncio
import json
import sys

import httpx

BASE = "http://localhost:8002/api/v1"

async def user_journey():
    async with httpx.AsyncClient(base_url="http://localhost:8002", timeout=60) as c:
        print("=" * 60)
        print("PromiseLink 用户旅程模拟")
        print("=" * 60)

        # Step 1: 打开首页
        print("\nStep 1: 打开首页")
        r = await c.get("/")
        print(f"   首页加载: {r.status_code}, HTML长度={len(r.text)}")
        assert r.status_code == 200, f"首页加载失败: {r.status_code}"
        assert "PromiseLink" in r.text, "首页缺少PromiseLink标题"

        # Step 2: 登录
        print("\nStep 2: 登录")
        r = await c.post(f"{BASE}/auth/login", json={"user_id": "demo-user", "poc_secret": "promiselink2026"})
        assert r.status_code == 200, f"登录失败: {r.status_code} {r.text}"
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("   登录成功")

        # Step 3: 录入交流记录
        print("\nStep 3: 录入交流记录")
        r = await c.post(f"{BASE}/events", headers=headers, json={
            "event_type": "meeting",
            "raw_text": "今天和张总见面，讨论了新项目合作。张总关心项目进度，我承诺下周三前提交方案。张总提到他们公司正在寻找AI解决方案供应商。",
            "source": "manual"
        })
        assert r.status_code in [200, 201], f"事件创建失败: {r.status_code} {r.text}"
        event = r.json()
        print(f"   事件创建成功: id={event['id'][:8]}...")

        # Step 4: 等待Pipeline处理
        print("\nStep 4: 等待Pipeline处理(LLM提取实体+生成待办)...")
        await asyncio.sleep(40)

        # Step 5: 查看实体
        print("\nStep 5: 查看提取的人物实体")
        r = await c.get(f"{BASE}/entities", headers=headers)
        assert r.status_code == 200, f"实体查询失败: {r.status_code}"
        entities_data = r.json()
        items = entities_data if isinstance(entities_data, list) else entities_data.get("items", [])
        for e in items[:5]:
            name = e.get("name", "?")
            etype = e.get("entity_type", "?")
            props = e.get("properties", {})
            concern = props.get("concern", "")
            capability = props.get("capability", "")
            print(f"   - {name} ({etype})")
            if concern:
                print(f"     关注: {concern}")
            if capability:
                print(f"     能力: {capability}")
        print(f"   共 {len(items)} 个实体")

        # Step 6: 查看待办
        print("\nStep 6: 查看AI生成的待办")
        r = await c.get(f"{BASE}/todos", headers=headers)
        assert r.status_code == 200, f"待办查询失败: {r.status_code}"
        todos_data = r.json()
        todo_items = todos_data if isinstance(todos_data, list) else todos_data.get("items", [])
        for t in todo_items[:5]:
            title = t.get("title", "?")[:50]
            status = t.get("status", "?")
            ttype = t.get("todo_type", "?")
            print(f"   - [{ttype}] {title} ({status})")
        print(f"   共 {len(todo_items)} 条待办")

        # Step 7: 查看Dashboard
        print("\nStep 7: 查看Dashboard")
        r = await c.get(f"{BASE}/dashboard/day-view", headers=headers)
        print(f"   Dashboard: {r.status_code}")

        # Step 8: 导出数据
        print("\nStep 8: 导出数据")
        r = await c.get(f"{BASE}/export/demo-user", headers=headers)
        assert r.status_code == 200, f"导出失败: {r.status_code}"
        data = json.loads(r.text)
        print(f"   导出: events={len(data.get('events', []))}, entities={len(data.get('entities', []))}, todos={len(data.get('todos', []))}")

        # Step 9: 文件上传
        print("\nStep 9: 上传会议纪要文件")
        files = {"file": ("meeting.txt", "和李总讨论了Q3销售策略，李总希望我们提供定制化方案。", "text/plain")}
        data_form = {"event_type": "meeting"}
        r = await c.post(f"{BASE}/events/upload", headers=headers, files=files, data=data_form)
        assert r.status_code in [200, 201], f"文件上传失败: {r.status_code} {r.text}"
        print("   文件上传成功")

        # Step 10: 查看关联
        print("\nStep 10: 查看关联")
        r = await c.get(f"{BASE}/associations", headers=headers)
        print(f"   关联: {r.status_code}")

        print("\n" + "=" * 60)
        print("用户旅程完成!")
        print("=" * 60)
        return True

if __name__ == "__main__":
    try:
        asyncio.run(user_journey())
    except Exception as e:
        print(f"\n❌ 用户旅程失败: {e}", file=sys.stderr)
        sys.exit(1)
