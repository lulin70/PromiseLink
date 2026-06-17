#!/usr/bin/env python3
"""End-to-end verification script for PromiseLink PoC.

Tests the full pipeline with real LLM calls (Moka AI).
Run: python scripts/e2e_verify.py

Verifies:
1. LLM client can call Moka AI API
2. Entity extraction from card_save and meeting events
3. Todo generation from extracted entities
4. Full pipeline: Event → Extract → Generate → Memory → Status
"""

import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Load .env
from dotenv import load_dotenv

load_dotenv(project_root / ".env")

from promiselink.config import Settings, get_settings
from promiselink.core.logging import configure_logging, get_logger
from promiselink.database import AsyncSessionLocal, close_db, init_db
from promiselink.models.event import Event
from promiselink.services.entity_extractor import EntityExtractor
from promiselink.services.entity_resolution import EntityResolutionEngine
from promiselink.services.event_pipeline import EventPipeline
from promiselink.services.llm_client import LLMClient
from promiselink.services.memory_provider import FileStoreProvider
from promiselink.services.todo_generator import TodoGenerator

configure_logging()
logger = get_logger("e2e_verify")


# ── Test Data ──

CARD_SAVE_RAW = json.dumps({
    "person": {
        "name": "张伟",
        "company": "智源AI研究院",
        "title": "首席科学家",
        "phone": "13812345678",
        "email": "zhangwei@baai.ac.cn",
        "city": "北京",
    },
    "interaction_context": {
        "their_concern": "正在寻找大模型落地场景的合作方",
        "my_promise": "下周发一份我们团队的AI应用案例集",
        "follow_up_hint": "他对多模态方向很感兴趣",
    },
}, ensure_ascii=False)

MEETING_RAW = """今天下午和盛恒资本的李总、王明一起开了投资对接会。

李总说他们最近一直在看AI赛道的早期项目，特别是大模型应用方向。
他提到手上有3个LP在找AI项目，希望我推荐靠谱的团队。

王明是李总的朋友，做技术咨询的，他说可以帮忙引荐几个AI创业团队。

我答应李总下周一前把AI项目资料整理好发给他。
李总也答应帮我们对接他LP的资源。

会议在国贸三期，大概聊了一个半小时。整体感觉合作机会很大。"""

TEST_USER_ID = str(uuid.UUID("00000000-0000-0000-0000-000000000001"))


# ── Verification Steps ──


async def verify_llm_client(settings: Settings) -> bool:
    """Step 1: Verify LLM client can call Moka AI API."""
    print("\n" + "=" * 60)
    print("Step 1: LLM Client 真实调用验证")
    print("=" * 60)

    llm = LLMClient(config=settings)
    try:
        result = await llm.call("请用一句话回答：1+1等于几？", max_tokens=20)
        print(f"  LLM响应: {result[:100]}")
        print("  ✅ LLM客户端调用成功")
        return True
    except Exception as e:
        print(f"  ❌ LLM客户端调用失败: {e}")
        return False
    finally:
        await llm.close()


async def verify_llm_json(settings: Settings) -> bool:
    """Step 2: Verify LLM JSON parsing."""
    print("\n" + "=" * 60)
    print("Step 2: LLM JSON 解析验证")
    print("=" * 60)

    llm = LLMClient(config=settings)
    try:
        result = await llm.call_json(
            '请返回一个JSON：{"answer": 2, "explanation": "1加1等于2"}。只返回JSON，不要其他内容。',
            max_tokens=50,
        )
        print(f"  解析结果: {json.dumps(result, ensure_ascii=False)[:200]}")
        if "answer" in result:
            print("  ✅ LLM JSON解析成功")
            return True
        else:
            print("  ❌ JSON缺少answer字段")
            return False
    except Exception as e:
        print(f"  ❌ LLM JSON解析失败: {e}")
        return False
    finally:
        await llm.close()


async def verify_entity_extraction(settings: Settings) -> bool:
    """Step 3: Verify entity extraction from card_save and meeting."""
    print("\n" + "=" * 60)
    print("Step 3: 实体抽取验证（真实LLM调用）")
    print("=" * 60)

    llm = LLMClient(config=settings)

    try:
        # Create in-memory DB session
        await init_db()
        async with AsyncSessionLocal() as session:
            async with session.begin():
                # Test card_save extraction
                print("\n  --- 3a: 名片抽取 (card_save) ---")
                event_card = Event(
                    id=str(uuid.uuid4()),
                    user_id=TEST_USER_ID,
                    event_type="card_save",
                    source="iamhere",
                    title="张伟名片",
                    raw_text=CARD_SAVE_RAW,
                    status="pending",
                )
                session.add(event_card)
                await session.flush()

                extractor = EntityExtractor(llm_client=llm, session=session)
                result = await extractor.extract_from_event(event_card)

                print(f"  提取人物数: {len(result.persons)}")
                for p in result.persons:
                    print(f"    - {p.name}: {p.title} @ {p.company}")
                    if p.resource:
                        print(f"      资源: {p.resource}")
                    if p.demand:
                        print(f"      需求: {p.demand}")
                print(f"  摘要: {result.summary[:100]}")

                if len(result.persons) > 0 and result.persons[0].name:
                    print("  ✅ 名片实体抽取成功")
                else:
                    print("  ❌ 名片实体抽取失败")
                    return False

            # Test meeting extraction (separate transaction)
            async with session.begin():
                print("\n  --- 3b: 会议抽取 (meeting) ---")
                event_meeting = Event(
                    id=str(uuid.uuid4()),
                    user_id=TEST_USER_ID,
                    event_type="meeting",
                    source="manual",
                    title="投资对接会",
                    raw_text=MEETING_RAW,
                    status="pending",
                )
                session.add(event_meeting)
                await session.flush()

                result2 = await extractor.extract_from_event(event_meeting)

                print(f"  提取人物数: {len(result2.persons)}")
                for p in result2.persons:
                    print(f"    - {p.name}: {p.title} @ {p.company or '未知'}")
                print(f"  关键词: {result2.keywords}")
                print(f"  摘要: {result2.summary[:100]}")

                if len(result2.persons) >= 2:
                    print("  ✅ 会议实体抽取成功")
                    return True
                else:
                    print("  ❌ 会议实体抽取失败（期望≥2人）")
                    return False

    except Exception as e:
        print(f"  ❌ 实体抽取异常: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await llm.close()


async def verify_todo_generation(settings: Settings) -> bool:
    """Step 4: Verify todo generation from event content."""
    print("\n" + "=" * 60)
    print("Step 4: Todo生成验证（真实LLM调用）")
    print("=" * 60)

    llm = LLMClient(config=settings)

    try:
        await init_db()
        async with AsyncSessionLocal() as session:
            async with session.begin():
                event = Event(
                    id=str(uuid.uuid4()),
                    user_id=TEST_USER_ID,
                    event_type="meeting",
                    source="manual",
                    title="投资对接会",
                    raw_text=MEETING_RAW,
                    status="pending",
                )
                session.add(event)
                await session.flush()

                generator = TodoGenerator(llm_client=llm, session=session)

                # Mock entities for todo generation
                from promiselink.models.entity import Entity
                entity1 = Entity(
                    id=str(uuid.uuid4()),
                    user_id=TEST_USER_ID,
                    entity_type="person",
                    name="李总",
                    canonical_name="李总",
                    properties={
                        "basic": {"company": "盛恒资本", "title": "投资总监"},
                    },
                    source_event_id=event.id,
                    status="confirmed",
                )
                entity2 = Entity(
                    id=str(uuid.uuid4()),
                    user_id=TEST_USER_ID,
                    entity_type="person",
                    name="王明",
                    canonical_name="王明",
                    properties={
                        "basic": {"company": "", "title": "技术咨询"},
                    },
                    source_event_id=event.id,
                    status="confirmed",
                )

                todos = await generator.generate_todos(
                    event=event,
                    entities=[entity1, entity2],
                )

                print(f"  生成Todo数: {len(todos)}")
                for t in todos:
                    print(f"    - [{t.todo_type}] {t.title} (优先级={t.priority})")

                if len(todos) > 0:
                    print("  ✅ Todo生成成功")
                    return True
                else:
                    print("  ❌ Todo生成失败（0个Todo）")
                    return False

    except Exception as e:
        print(f"  ❌ Todo生成异常: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await llm.close()


async def verify_full_pipeline(settings: Settings) -> bool:
    """Step 5: Verify full pipeline end-to-end."""
    print("\n" + "=" * 60)
    print("Step 5: 完整管线验证（Event→Extract→Todo→Memory→Status）")
    print("=" * 60)

    llm = LLMClient(config=settings)
    memory = FileStoreProvider(base_dir=str(project_root / "data" / "memory"))

    try:
        await init_db()
        async with AsyncSessionLocal() as session:
            async with session.begin():
                event = Event(
                    id=str(uuid.uuid4()),
                    user_id=TEST_USER_ID,
                    event_type="meeting",
                    source="manual",
                    title="投资对接会",
                    raw_text=MEETING_RAW,
                    status="pending",
                )
                session.add(event)
                await session.flush()

                resolution_engine = EntityResolutionEngine(
                    session=session,
                    auto_merge_threshold=settings.entity_resolution_auto_merge_threshold,
                    confirm_threshold=settings.entity_resolution_human_review_threshold,
                    llm_client=llm,
                )

                pipeline = EventPipeline(
                    llm_client=llm,
                    session=session,
                    resolution_engine=resolution_engine,
                    memory_provider=memory,
                )

                result = await pipeline.process(event)

                print(f"  管线状态: {result.status}")
                print(f"  提取实体数: {len(result.entities)}")
                print(f"  生成Todo数: {len(result.todos)}")
                print(f"  事件状态: {event.status}")
                print(f"  错误: {result.error or '无'}")

                for e in result.entities:
                    print(f"    实体: {e.name} ({e.entity_type})")
                for t in result.todos:
                    print(f"    Todo: [{t.todo_type}] {t.title}")

                if result.success and len(result.entities) > 0 and len(result.todos) > 0:
                    print("  ✅ 完整管线验证成功")

                    # Verify memory was stored
                    entries = await memory.get_by_entity(str(result.entities[0].id))
                    print(f"  知识库记录数: {len(entries)}")
                    return True
                else:
                    print(f"  ❌ 完整管线验证失败: status={result.status}, error={result.error}")
                    return False

    except Exception as e:
        print(f"  ❌ 完整管线异常: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await llm.close()


async def main():
    """Run all verification steps."""
    print("=" * 60)
    print("PromiseLink PoC 端到端验证")
    print(f"时间: {datetime.now().isoformat()}")
    print("=" * 60)

    settings = get_settings()
    print("\nLLM配置:")
    print(f"  Provider: {settings.llm_provider}")
    print(f"  Base URL: {settings.llm_base_url}")
    print(f"  Model: {settings.llm_model}")
    print(f"  API Key: {settings.llm_api_key[:8]}..." if settings.llm_api_key else "  API Key: 未设置")

    results = {}

    # Step 1: LLM client basic call
    results["llm_call"] = await verify_llm_client(settings)

    # Step 2: LLM JSON parsing
    results["llm_json"] = await verify_llm_json(settings)

    # Step 3: Entity extraction (real LLM)
    results["entity_extraction"] = await verify_entity_extraction(settings)

    # Step 4: Todo generation (real LLM)
    results["todo_generation"] = await verify_todo_generation(settings)

    # Step 5: Full pipeline
    results["full_pipeline"] = await verify_full_pipeline(settings)

    # Summary
    print("\n" + "=" * 60)
    print("验证结果汇总")
    print("=" * 60)
    for step, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {step}: {status}")

    all_passed = all(results.values())
    print(f"\n总体结果: {'✅ 全部通过' if all_passed else '❌ 存在失败'}")

    # Cleanup
    await close_db()

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
