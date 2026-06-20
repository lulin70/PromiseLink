"""Step 11: Generate todos from new associations — Link → Action."""

from __future__ import annotations

import time

from sqlalchemy import select

from promiselink.core.logging import get_logger
from promiselink.models.entity import Entity
from promiselink.models.todo import Todo
from promiselink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("promiselink.pipeline_steps")


class Step11_AssociationTodos(PipelineStep):
    """Generate todos from new associations — Link → Action."""

    name = "step11_association_todos"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from promiselink.database import AsyncSessionLocal, commit_with_retry

        event_id = context.event_id
        user_id = context.user_id
        assert context.result is not None

        _t7_5 = time.monotonic()
        try:
            async with AsyncSessionLocal() as session:
                from promiselink.models.association import Association

                assoc_result = await session.execute(
                    select(Association).where(
                        Association.user_id == user_id,
                        Association.source_event_id == event_id,
                    )
                )
                new_assocs = assoc_result.scalars().all()

                if new_assocs:
                    # Only fetch entities involved in associations (not all user entities)
                    entity_ids = set()
                    for assoc in new_assocs:
                        entity_ids.add(str(assoc.source_entity_id))
                        entity_ids.add(str(assoc.target_entity_id))
                    ent_result = await session.execute(
                        select(Entity.id, Entity.name).where(Entity.id.in_(entity_ids))
                    )
                    entity_map = {str(eid): name for eid, name in ent_result.all()}

                    for assoc in new_assocs:
                        src_name = entity_map.get(str(assoc.source_entity_id), "")
                        tgt_name = entity_map.get(str(assoc.target_entity_id), "")
                        todo_title = None
                        todo_type = "followup"
                        priority = 3

                        atype = assoc.association_type
                        evidence = (assoc.properties or {}).get("evidence", {})

                        if atype == "industry_chain":
                            rel = evidence.get("relation", "")
                            if rel == "potential_investor_startup":
                                todo_title = f"引荐{src_name}和{tgt_name}（投资-创业链）"
                                todo_type = "cooperation_signal"
                                priority = 1
                            else:
                                todo_title = f"对接{src_name}和{tgt_name}（产业链上下游）"
                                todo_type = "followup"
                                priority = 3
                        elif atype == "supply_demand":
                            matches = evidence.get("matches", [])
                            if matches:
                                m = matches[0]
                                items = ", ".join(m.get("matched_items", [])[:2])
                                todo_title = f"{m.get('supplier', src_name)} 可帮助 {m.get('requester', tgt_name)} ({items})"
                                todo_type = "help"
                                priority = 1
                        elif atype == "topic_overlap":
                            todo_title = f"安排{src_name}和{tgt_name}交流（同领域）"
                            todo_type = "followup"
                            priority = 3
                        elif atype == "same_city":
                            todo_title = f"约{src_name}和{tgt_name}同城见面"
                            todo_type = "care"
                            priority = 4

                        if todo_title:
                            existing = await session.execute(
                                select(Todo).where(
                                    Todo.user_id == user_id,
                                    Todo.title == todo_title,
                                    Todo.status == "pending",
                                )
                            )
                            if not existing.scalar_one_or_none():
                                todo = Todo(
                                    user_id=user_id,
                                    title=todo_title,
                                    todo_type=todo_type,
                                    priority=priority,
                                    status="pending",
                                    source_event_id=event_id,
                                )
                                session.add(todo)

                    await commit_with_retry(session)
        except Exception as step12_err:  # Broadened — DB failure logs and continues pipeline
            logger.warning("pipeline_step12_error", error=str(step12_err))
            context.failed_steps.append(self.name)

        context.result.step_timings["step11_assoc_todos"] = time.monotonic() - _t7_5

        return context
