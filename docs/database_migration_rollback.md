# PromiseLink 数据库迁移回滚指南

> **版本**: v1.1  
> **更新日期**: 2026年9月21日  
> **适用场景**: 生产环境迁移失败回滚、版本降级

---

## 概述

本文档描述如何安全回滚Alembic数据库迁移，确保在生产环境遇到问题时能快速恢复。

> **适用范围说明（2026-09-19 更新）**：**基础版仅使用 SQLite**（`DATABASE_URL` 默认 `sqlite:///{用户家目录}/.promiselink/data/promiselink.db`），基础版 PostgreSQL 后端支持已随方案 B 移除（详见 PromiseLink-Pro `docs/review/PROJECT_REVIEW_20260918_FINDINGS.md` §9）。本文档中所有 **PostgreSQL 相关步骤（`pg_dump`/`pg_restore`/`pg_stat_activity`/`psql` 等）仅适用于定制版（团队/多租户）**；基础版请只参考 SQLite 部分。

---

## 前置准备

### 1. 迁移前备份

**强制要求**：任何生产环境迁移前必须备份数据库。

```bash
# SQLite备份
cp data/promiselink.db data/promiselink.db.backup.$(date +%Y%m%d_%H%M%S)

# PostgreSQL备份
pg_dump -U promiselink -h localhost -d promiselink_pro \
  -F c -b -v -f backup_$(date +%Y%m%d_%H%M%S).dump
```

### 2. 查看当前迁移状态

```bash
# 查看当前版本
alembic current

# 查看迁移历史
alembic history --verbose

# 示例输出：
# Rev: abc123def456 (head)
# Parent: <base>
# Path: migrations/versions/abc123def456_initial.py
```

---

## 回滚方法

### 方法1：按版本号回滚（推荐）

回滚到指定版本：

```bash
# 查看可用版本
alembic history

# 回滚到特定版本
alembic downgrade <revision_id>

# 示例：回滚到初始版本
alembic downgrade abc123def456
```

### 方法2：回滚N个版本

```bash
# 回滚1个版本
alembic downgrade -1

# 回滚2个版本
alembic downgrade -2

# 回滚所有版本（危险！）
alembic downgrade base
```

### 方法3：使用备份恢复

如果迁移脚本损坏或回滚失败：

```bash
# SQLite：直接替换数据库文件
mv data/promiselink.db data/promiselink.db.failed
cp data/promiselink.db.backup.20260629_210000 data/promiselink.db

# PostgreSQL：使用pg_restore
dropdb -U promiselink promiselink_pro
createdb -U promiselink promiselink_pro
pg_restore -U promiselink -h localhost -d promiselink_pro \
  backup_20260629_210000.dump
```

---

## 回滚验证

回滚后必须验证：

```bash
# 1. 检查当前版本
alembic current
# 应显示目标版本

# 2. 验证数据完整性
python -c "
from promiselink.core.database import engine, Base
from promiselink.models import *
from sqlalchemy import inspect
inspector = inspect(engine)
print('Tables:', inspector.get_table_names())
"

# 3. 运行测试
pytest tests/test_models.py -v

# 4. 启动服务验证
uvicorn promiselink.main:app --port 8000 &
sleep 5
curl http://localhost:8000/api/v1/health
kill %1
```

---

## 常见回滚场景

### 场景1：新字段导致的兼容性问题

**问题**：添加非空字段但无默认值。

**回滚步骤**：
```bash
# 1. 停止服务
sudo systemctl stop promiselink

# 2. 回滚迁移
alembic downgrade -1

# 3. 验证表结构
sqlite3 data/promiselink.db ".schema entities"

# 4. 重启服务
sudo systemctl start promiselink
```

### 场景2：外键约束冲突

**问题**：新增外键导致现有数据违反约束。

**回滚步骤**：
```bash
# 1. 导出有问题的数据
python scripts/export_conflict_data.py

# 2. 回滚迁移
alembic downgrade <previous_version>

# 3. 修复数据
python scripts/fix_conflict_data.py

# 4. 重新执行迁移
alembic upgrade head
```

### 场景3：索引创建超时

**问题**：大表创建索引导致锁表超时。

**回滚步骤**：
```bash
# 1. 查看锁表情况（PostgreSQL）
SELECT * FROM pg_stat_activity WHERE state = 'active';

# 2. 终止迁移进程
SELECT pg_terminate_backend(pid) FROM pg_stat_activity 
WHERE query LIKE '%CREATE INDEX%';

# 3. 回滚迁移
alembic downgrade -1

# 4. 使用CONCURRENTLY创建索引（不锁表）
# 修改迁移脚本：op.create_index(..., postgresql_concurrently=True)
```

### 场景4：修订 id 改名导致 `Can't locate revision`（L-11）

**问题**：`alembic upgrade head` 报

```
ERROR [alembic.util.messaging] Can't locate revision identified by 'merge_w5_double_scope_7bb48953af15'
FAILED: Can't locate revision identified by 'merge_w5_double_scope_7bb48953af15'
```

**背景**：该修订 id 曾在提交 `76aba28`（2026-09-18）中**改名**，由 `merge_w5_double_scope_7bb48953af15`（34 字符）改为 `merge_w5_double_scope` —— 目的是修 `alembic_version.version_num` 的 `VARCHAR(32)` 截断（详见 CHANGELOG 1.1.x 条目）。改名让**历史链里的旧 id 不再存在**，但已经落库的 `version_num` 仍写着旧 id，于是 alembic 无法定位起点。

**影响面（已核实，不要夸大）**：

- **已发布版本的用户不受影响** —— v1.1.0 起的 head 一直是 `w5a_score_audit_logs`，该 id 至今未变。
- 受影响的**只有**在 2026-09-10 ~ 09-13 之间迁移过、且 `version_num` 停在**中间 head**（即 `merge_w5_double_scope_7bb48953af15`）的开发库 / 预发库。

**处置办法（在 SQLite 上实测三种路径，结论见下）**：

```bash
# 前置：先看库停在哪
alembic current          # 若同样报 Can't locate revision，改用 SQL 直查：
sqlite3 <db> "SELECT version_num FROM alembic_version;"

# 路径 1（推荐）：--purge 直接改写版本标记，再做一次 upgrade
alembic stamp --purge merge_w5_double_scope
alembic upgrade head

# 路径 2（等价）：直接改表，绕过 alembic 的起点解析
sqlite3 <db> "UPDATE alembic_version SET version_num='merge_w5_double_scope';"
alembic upgrade head

# 路径 3（开发库最省事）：该库只用于本地开发时，直接删库重建
rm <db> && alembic upgrade head
```

**❌ 不要这样做**（两条都是"看起来最自然"的做法，实测均失败）：

```bash
alembic upgrade head                              # 仍然报 Can't locate revision
alembic stamp merge_w5_double_scope               # 同样报 Can't locate revision
```

原因：`alembic stamp` **不带 `--purge`** 时会先解析当前版本以计算迁移路径，起点解析失败即中止；只有 `--purge` 会跳过这一步、直接覆写 `alembic_version`。

**❌ 也不要在历史链里补一个同名的假修订**：那会在 alembic 迁移链中永久留下一个非真实节点，把一次性便利变成长期负担。

**验证与反向探针（2026-09-21 实测，可复现）**：

| 探针 | 动作 | 实测结果 |
|---|---|---|
| 基线 | 全新库 `alembic upgrade head` | ✅ 落盘 `w5a_score_audit_logs`，`score_audit_logs` 表建成 |
| 反向 | 把 `version_num` 改为旧 id 后直接 `upgrade head` | ❌ `Can't locate revision` ×2（与本节症状一致） |
| 反向 | 旧 id + `alembic stamp <新id>`（无 `--purge`） | ❌ `Can't locate revision` ×2（印证"路径 1 必须带 `--purge`"） |
| 修复 | 旧 id + `stamp --purge` + `upgrade head` | ✅ 落盘 `w5a_score_audit_logs` |
| 修复 | 旧 id + SQL `UPDATE` + `upgrade head` | ✅ 落盘 `w5a_score_audit_logs` |

---

## 回滚失败的应急处理

### 1. 迁移脚本错误

如果downgrade()函数有bug：

```bash
# 临时跳过有问题的迁移
alembic stamp <target_revision>

# 手动修复数据库
psql -U promiselink -d promiselink_pro <<EOF
-- 手动执行回滚SQL
DROP TABLE IF EXISTS new_table;
ALTER TABLE old_table DROP COLUMN new_column;
EOF

# 更新alembic版本标记
alembic stamp head
```

### 2. 数据丢失风险

如果回滚会丢失数据：

```bash
# 1. 导出关键数据
python scripts/export_critical_data.py --table=entities

# 2. 执行回滚
alembic downgrade -1

# 3. 重新导入数据
python scripts/import_critical_data.py --file=entities_backup.json
```

---

## 预防措施

### 1. 编写可逆迁移

每个upgrade()必须有对应的downgrade()：

```python
def upgrade():
    # 添加字段
    op.add_column('entities', sa.Column('new_field', sa.String(100), nullable=True))
    
def downgrade():
    # 删除字段
    op.drop_column('entities', 'new_field')
```

### 2. 分阶段迁移

复杂变更分多个版本：

```python
# 版本1：添加可空字段
def upgrade():
    op.add_column('entities', sa.Column('status', sa.String(20), nullable=True))

# 版本2：填充默认值
def upgrade():
    op.execute("UPDATE entities SET status='active' WHERE status IS NULL")

# 版本3：设为非空
def upgrade():
    op.alter_column('entities', 'status', nullable=False)
```

### 3. 测试回滚流程

在Staging环境验证：

```bash
# 1. 升级
alembic upgrade head

# 2. 回滚
alembic downgrade -1

# 3. 再次升级
alembic upgrade head

# 确保往返迁移都成功
```

---

## 回滚检查清单

迁移前：
- [ ] 数据库已备份
- [ ] 迁移脚本已在测试环境验证
- [ ] downgrade()函数已测试
- [ ] 服务已停止（或设为只读模式）

回滚后：
- [ ] 当前版本正确（alembic current）
- [ ] 表结构正确
- [ ] 数据完整性验证通过
- [ ] 测试用例通过
- [ ] 服务启动正常
- [ ] API健康检查通过

---

## 生产环境回滚SOP

```bash
#!/bin/bash
# 生产环境紧急回滚脚本

set -e

echo "=== Step 1: 停止服务 ==="
sudo systemctl stop promiselink
sudo systemctl stop promiselink-gateway

echo "=== Step 2: 备份当前状态 ==="
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
cp data/promiselink.db data/promiselink.db.before_rollback.$TIMESTAMP

echo "=== Step 3: 回滚迁移 ==="
alembic downgrade -1

echo "=== Step 4: 验证数据库 ==="
python -m pytest tests/test_models.py -v

echo "=== Step 5: 重启服务 ==="
sudo systemctl start promiselink
sleep 5

echo "=== Step 6: 健康检查 ==="
curl -f http://localhost:8000/api/v1/health || {
  echo "健康检查失败，回滚失败！"
  exit 1
}

echo "=== 回滚完成 ==="
```

---

## 联系支持

- **紧急情况**: support@promiselink.cn
- **工单系统**: https://support.promiselink.cn
- **文档中心**: https://docs.promiselink.cn

---

**最后更新**: 2026年9月21日  
**维护者**: PromiseLink团队
