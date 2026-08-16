-- ============================================================================
-- PromiseLink 基础版 — 身份统一数据迁移脚本 (v0.9.7)
-- ----------------------------------------------------------------------------
-- 目标：将所有业务表（events/entities/todos/associations）中分散的多个
--       user_id 合并到单一 local_user，解决小程序与本地浏览器数据不一致。
--
-- 用法：
--   1) 备份：  cp data/promiselink_poc.db data/promiselink_poc.db.bak
--   2) 执行：  sqlite3 data/promiselink_poc.db < scripts/migrate_to_local_user.sql
--   3) 验证：  脚本末尾的 SELECT 应全部返回 distinct_users = 1
--
-- 注意：迁移后测试/演示数据（e2e_*、UUID、wxid_* 等）会合并到 local_user，
--       这是期望行为（清理历史污染）。执行前务必先备份。
-- ============================================================================

BEGIN TRANSACTION;

-- 1. 迁移 events
UPDATE events SET user_id = 'local_user' WHERE user_id != 'local_user';

-- 2. 迁移 entities
UPDATE entities SET user_id = 'local_user' WHERE user_id != 'local_user';

-- 3. 迁移 todos（含承诺，承诺以 todo_type='promise' 存储在 todos 表）
UPDATE todos SET user_id = 'local_user' WHERE user_id != 'local_user';

-- 4. 迁移 associations
UPDATE associations SET user_id = 'local_user' WHERE user_id != 'local_user';

-- 5. 迁移 relationship_briefs（2026-08-16 补充：v0.9.7 初版迁移遗漏本表，
--    导致小程序/基础版关系页只剩 7 阶段进度条——brief 查询 404，
--    所有模块（最近互动/对方关注/我方承诺/下一步建议）不渲染）
UPDATE relationship_briefs SET user_id = 'local_user' WHERE user_id != 'local_user';

-- 6. 验证：各表 distinct user_id 数（预期均为 1）
SELECT 'events' AS tbl, COUNT(DISTINCT user_id) AS distinct_users FROM events
UNION ALL
SELECT 'entities', COUNT(DISTINCT user_id) FROM entities
UNION ALL
SELECT 'todos', COUNT(DISTINCT user_id) FROM todos
UNION ALL
SELECT 'associations', COUNT(DISTINCT user_id) FROM associations
UNION ALL
SELECT 'relationship_briefs', COUNT(DISTINCT user_id) FROM relationship_briefs;

COMMIT;
