"""DependencyAnalyzer — Full graph path analysis for Todo dependency scoring.

Implements F-55: Dependency dimension for Phase 1 four-dimensional priority model.
Detects blocking chains in the promise dependency graph.

Design reference: PromiseLink_技术设计_v1.md v2.7 §4.10.1a
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.logging import get_logger
from promiselink.models.todo import Todo

logger = get_logger("promiselink.dependency_analyzer")


class DependencyAnalyzer:
    """Analyze Todo dependency from the Association graph.

    Phase 1: Full graph path analysis
    - Build a directed promise dependency graph
    - Detect blocking chains (who is waiting for whom)
    - Support indirect dependencies up to 3 hops

    Score formula: dependency_score = Σ(1/depth) × min(1.0, blocked_count × 0.3)
    """

    MAX_DEPTH = 3  # Maximum dependency chain depth

    async def compute_dependency_score(self, todo: Todo, session: AsyncSession) -> float:
        """Compute dependency score for a Todo (0.0 ~ 1.0).

        Only promise and help type Todos have dependency scores.
        Other types return 0.0.

        Args:
            todo: The Todo to score
            session: AsyncSession for DB queries

        Returns:
            Dependency score between 0.0 and 1.0
        """
        if todo.todo_type not in ("promise", "help"):
            return 0.0

        # Step 1: Build promise dependency graph
        dep_graph = await self._build_promise_dependency_graph(str(todo.user_id), session)

        # Step 2: Find blocking chains from this Todo
        blocking_chains = self._find_blocking_chains(todo, dep_graph)

        if not blocking_chains:
            return 0.0

        # Step 3: Compute dependency score
        # blocked_count includes the chain end itself (it is blocked) + downstream
        score = 0.0
        for chain in blocking_chains:
            depth = len(chain)
            blocked_count = 1 + self._count_blocked_todos(chain[-1], dep_graph)
            score += (1.0 / depth) * min(1.0, blocked_count * 0.3)

        result = min(1.0, score)

        logger.debug(
            "dependency_score_computed",
            todo_id=str(todo.id),
            score=result,
            chains=len(blocking_chains),
        )

        return result

    async def _build_promise_dependency_graph(
        self, user_id: str, session: AsyncSession
    ) -> dict[str, list[str]]:
        """Build a directed promise dependency graph.

        Nodes: Todo IDs
        Edges: Todo A → Todo B means "A must complete before B can proceed"

        Logic: If two Todos relate to the same Entity, and one is my_promise
        while the other is their_promise, then my_promise is a prerequisite
        for their_promise.

        Args:
            user_id: User ID to scope the graph
            session: AsyncSession

        Returns:
            Dict mapping todo_id to list of dependent todo_ids
        """
        # Query all pending promise/help Todos for this user
        result = await session.execute(
            select(Todo).where(
                Todo.user_id == user_id,
                Todo.status == "pending",
                Todo.todo_type.in_(["promise", "help"]),
            )
        )
        todos = result.scalars().all()

        # Group Todos by related_entity_id
        graph: dict[str, list[str]] = {}
        entity_todos: dict[str, list[Todo]] = {}

        for t in todos:
            if t.related_entity_id:
                entity_todos.setdefault(str(t.related_entity_id), []).append(t)

        # Build dependency edges
        for entity_id, entity_todo_list in entity_todos.items():
            my_promises = [
                t for t in entity_todo_list if t.action_type == "my_promise"
            ]
            their_promises = [
                t for t in entity_todo_list if t.action_type == "their_promise"
            ]

            # My promise is a prerequisite for their promise
            for mp in my_promises:
                for tp in their_promises:
                    graph.setdefault(str(mp.id), []).append(str(tp.id))

        return graph

    def _find_blocking_chains(
        self, todo: Todo, graph: dict[str, list[str]]
    ) -> list[list[str]]:
        """BFS to find blocking chains from this Todo.

        A blocking chain means: if this Todo is completed,
        the dependent Todos can proceed.

        Args:
            todo: The Todo to start from
            graph: The dependency graph

        Returns:
            List of chains, each chain is a list of Todo IDs
        """
        chains = []
        todo_id = str(todo.id)
        visited = set()
        queue: list[list[str]] = [[todo_id]]

        while queue:
            chain = queue.pop(0)
            current = chain[-1]

            dependents = graph.get(current, [])
            for dep_id in dependents:
                if dep_id not in visited:
                    visited.add(dep_id)
                    new_chain = chain + [dep_id]
                    if len(new_chain) <= self.MAX_DEPTH:
                        chains.append(new_chain)
                        queue.append(new_chain)

        return chains

    def _count_blocked_todos(
        self, todo_id: str, graph: dict[str, list[str]]
    ) -> int:
        """Count how many Todos are blocked by this Todo.

        Args:
            todo_id: The blocking Todo ID
            graph: The dependency graph

        Returns:
            Number of blocked Todos
        """
        count = 0
        visited = set()
        queue = [todo_id]

        while queue:
            current = queue.pop(0)
            for dep_id in graph.get(current, []):
                if dep_id not in visited:
                    visited.add(dep_id)
                    count += 1
                    queue.append(dep_id)

        return count
