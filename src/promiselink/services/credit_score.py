"""Credit score calculation service with batch query support."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.models.todo import Todo
from promiselink.models.event import Event


class CreditScoreService:
    """Batch-capable credit score calculation.

    Score = my_fulfillment*40% + their_fulfillment*35% + consistency*15% + timeliness*10%
    Grade: A+(>=90) A(80-89) B(70-79) C(60-69) D(<60)
    """

    @staticmethod
    async def batch_calculate(
        session: AsyncSession,
        entity_ids: list[str],
        user_id: str,
    ) -> dict[str, dict]:
        """Calculate credit scores for multiple entities in batch.

        Executes 3 batch queries instead of N*4 per-entity queries.

        Returns:
            dict mapping entity_id -> score_data dict with keys:
            score, grade, my_fulfillment_rate, their_fulfillment_rate,
            interaction_consistency, total_interactions
        """
        if not entity_ids:
            return {}

        # ── Batch query 1: My promises (total + fulfilled) ──
        my_promises_q = (
            select(
                Todo.related_entity_id,
                func.count().label("total"),
                func.sum(
                    func.cast(Todo.fulfillment_status == "fulfilled", type_=None)
                ).label("fulfilled"),
            )
            .where(
                Todo.user_id == user_id,
                Todo.related_entity_id.in_(entity_ids),
                Todo.action_type == "my_promise",
            )
            .group_by(Todo.related_entity_id)
        )
        my_rows = dict((await session.execute(my_promises_q)).all())
        # my_rows: entity_id -> (total, fulfilled)

        # ── Batch query 2: Their promises (total + fulfilled) ──
        their_promises_q = (
            select(
                Todo.related_entity_id,
                func.count().label("total"),
                func.sum(
                    func.cast(Todo.fulfillment_status == "fulfilled", type_=None)
                ).label("fulfilled"),
            )
            .where(
                Todo.user_id == user_id,
                Todo.related_entity_id.in_(entity_ids),
                Todo.action_type == "their_promise",
            )
            .group_by(Todo.related_entity_id)
        )
        their_rows = dict((await session.execute(their_promises_q)).all())
        # their_rows: entity_id -> (total, fulfilled)

        # ── Batch query 3: Total interactions (all todos per entity) ──
        total_q = (
            select(
                Todo.related_entity_id,
                func.count().label("total"),
            )
            .where(
                Todo.user_id == user_id,
                Todo.related_entity_id.in_(entity_ids),
            )
            .group_by(Todo.related_entity_id)
        )
        total_rows = dict((await session.execute(total_q)).all())
        # total_rows: entity_id -> total_count

        # ── Build results ──
        results: dict[str, dict] = {}
        for eid in entity_ids:
            my_data = my_rows.get(eid)
            my_total = my_data[0] if my_data else 0
            my_fulfilled = my_data[1] if my_data else 0

            their_data = their_rows.get(eid)
            their_total = their_data[0] if their_data else 0
            their_fulfilled = their_data[1] if their_data else 0

            total_interactions = total_rows.get(eid, 0)

            my_rate = my_fulfilled / my_total if my_total > 0 else 0.5
            their_rate = their_fulfilled / their_total if their_total > 0 else 0.5

            # Interaction consistency
            if total_interactions >= 2:
                consistency = min(100, total_interactions * 10)
            else:
                consistency = 50

            # Response timeliness
            timeliness = (my_rate + their_rate) / 2 * 100

            # Weighted score
            score = (
                my_rate * 100 * 0.40
                + their_rate * 100 * 0.35
                + consistency * 0.15
                + timeliness * 0.10
            )

            # Grade mapping
            if score >= 90:
                grade = "A+"
            elif score >= 80:
                grade = "A"
            elif score >= 70:
                grade = "B"
            elif score >= 60:
                grade = "C"
            else:
                grade = "D"

            results[eid] = {
                "score": score,
                "grade": grade,
                "my_fulfillment_rate": round(my_rate, 3),
                "their_fulfillment_rate": round(their_rate, 3),
                "interaction_consistency": round(consistency, 1),
                "total_interactions": total_interactions,
            }

        return results

    @staticmethod
    async def calculate(
        session: AsyncSession,
        entity_id: str,
        user_id: str,
    ) -> dict:
        """Calculate credit score for a single entity (convenience wrapper)."""
        results = await CreditScoreService.batch_calculate(
            session, [entity_id], user_id
        )
        return results.get(entity_id, {
            "score": 0,
            "grade": "D",
            "my_fulfillment_rate": 0.5,
            "their_fulfillment_rate": 0.5,
            "interaction_consistency": 50,
            "total_interactions": 0,
        })
