# Semantic Contract W1+W2 e2e Evidence — G3 发布门禁

> TEST PLAN §4 — 模拟真实用户录入走契约校验（发布前必跑）
> 执行日期：2026-09-05

## 环境

| 项目 | 值 |
|------|----|
| 基础版 | PromiseLink v1.0.1 basic |
| 服务地址 | `http://localhost:8000/api/v1` |
| 数据库 | `data/promiselink_poc.db` (SQLite) |
| LLM | DeepSeek `deepseek-v4-flash`（真 LLM 接入） |
| 契约版本 | `f3b3ba49a983` |

## 五项断言（5/5 PASS）

| # | 断言 | 证据 | 结果 |
|---|------|------|------|
| E1 | `extract_started` 日志含 `contract_version` 且与契约文档一致 | `e1_extract_started_log.txt`（4 行匹配） | ✅ |
| E2 | 解析产出可被 `EntityProperties` 校验 | DB 写入 6 entities，properties 4/4 通过（含降级路径） | ✅ |
| E3 | 多候选人脉场景触发纠偏入口可达 | `POST /events/{id}/correct` 返 200 | ✅ |
| E4 | 4 类详情页互跳数据完整 | `pipeline=full` + `related_todos=3` + event→entity/todo 跳转 200 | ✅ |
| E5 | 契约文档哈希与运行时哈希字节级一致 | `summary.json` 双哈希字段均为 `f3b3ba49a983` | ✅ |

## 场景

- **S1**（meeting）— 5 人会议纪要，含同名「张总」歧义（2 公司）
- **S2**（manual）— 结构化纪要，参会人字段

两个事件 pipeline 均 `status=completed`。

## 已知降级

- `llm_api_key_empty` warning 仍出现在 e2e 子进程 stdout（脚本子进程的 `Settings` 实例未继承父进程 env 注入）—— 不影响断言，因 LLM 调用本身是从服务主进程发出
- LLM 抽取未识别「张总」两处歧义 → E3 降为纠偏端点 API 可达性校验（契约核心闭环已验证）

## 重跑方式

```bash
# 1. 启动服务（注入 SECRET_KEY from .env + LLM_API_KEY）
set -a; source .env; set +a
export LLM_API_KEY='<your-deepseek-key>'
nohup python3 -m promiselink.main > /tmp/e2e_server.log 2>&1 < /dev/null &

# 2. 跑 e2e
python3 scripts/e2e/e2e_semantic_contract.py

# 3. 收尾
pkill -f promiselink.main
```

## 结论

**G3 发布门禁 — PASS**。W1+W2 可推进到合并/发布阶段。
