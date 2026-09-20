"""Alembic 修订树契约守卫（fail-closed）。

历史成因（2026-09-18）：CI ``e2e`` job 的 ``alembic upgrade head`` 当时跑在
PostgreSQL 上，以 ``psycopg2.errors.StringDataRightTruncation: value too long
for type character varying(32)`` 失败 —— 两个修订 id 分别长 33/34 字符，而
alembic 建 ``alembic_version`` 表时把 ``version_num`` 固定为 ``VARCHAR(32)``。

守卫保留理由：32 字符上限来自 alembic 自身的 DDL，与后端无关。基础版自
2026-09-19 起已收敛为 SQLite 单后端（PostgreSQL 支持随 Docker 交付链一并
移除，见 ``PromiseLink-Pro/docs/review/PROJECT_REVIEW_20260918_FINDINGS.md``
§9），而 SQLite 不校验 ``VARCHAR`` 长度——正因如此，这类超长 id 不会在本地
暴露，只能靠本测试在提交前拦下。任何超长修订 id 或双 head 都在此失败。
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

# alembic 在 ``alembic/runtime/migration.py`` 中固定使用 ``sa.String(32)``
# 建 ``alembic_version.version_num``；超出即违反 alembic 的 DDL 契约。
REVISION_ID_LIMIT = 32


def _scripts() -> ScriptDirectory:
    """解析仓库内的 alembic 修订树（不连接数据库）。"""
    repo_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(repo_root / "src" / "promiselink" / "alembic")
    )
    return ScriptDirectory.from_config(cfg)


def _parents(revision: object) -> list[str]:
    down = getattr(revision, "down_revision", None)
    if down is None:
        return []
    if isinstance(down, str):
        return [down]
    return list(down)


def test_revision_ids_fit_alembic_version_column() -> None:
    too_long = {
        rev.revision: len(rev.revision)
        for rev in _scripts().walk_revisions()
        if len(rev.revision) > REVISION_ID_LIMIT
    }
    assert not too_long, (
        f"修订 id 超过 alembic_version.version_num 的 {REVISION_ID_LIMIT} 字符上限"
        f"（alembic 固定 VARCHAR(32)）：{too_long}"
    )


def test_single_head() -> None:
    heads = list(_scripts().get_heads())
    assert len(heads) == 1, f"修订树必须只有一个 head，实际 {len(heads)}: {heads}"


def test_every_down_revision_resolves() -> None:
    scripts = _scripts()
    known = {rev.revision for rev in scripts.walk_revisions()}
    dangling = {
        parent
        for rev in scripts.walk_revisions()
        for parent in _parents(rev)
        if parent not in known
    }
    assert not dangling, f"存在无法解析的 down_revision: {sorted(dangling)}"
