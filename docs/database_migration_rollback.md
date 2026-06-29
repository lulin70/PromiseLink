# PromiseLink 数据库迁移回滚指南

> **版本**: v1.0  
> **更新日期**: 2026年6月29日  
> **适用场景**: 生产环境迁移失败回滚、版本降级

---

## 概述

本文档描述如何安全回滚Alembic数据库迁移，确保在生产环境遇到问题时能快速恢复。

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

**最后更新**: 2026年6月29日  
**维护者**: PromiseLink团队
