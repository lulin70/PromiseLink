# PromiseLink 部署规范 v1.1

> **版本**: v1.1（2026-09-13 升级；针对 v1.0-rc1 release 期间暴露的"tag↔VERSION 不一致" + "download.html 长期指向错链"问题，在 `build.yml` 引入 tag↔VERSION 一致性门禁 + 正则化 sed + 部署自检）
> **范围**: 基础版 + 官方服务器 + GitHub Release 三者间的边界、职责与协作
> **目的**: 一次写清，以后引用——避免反复出现"该 Docker 的没 Docker、该更新的没更新"的低级失误
> **状态**: 强制约束；本规范的任何变更需在 PR 中说明理由 + 同步更新 tracker

---

## §0 经验教训（先看这段）

### 教训 1：基础版不需要 Docker，但容易误用 Docker

**误判**：看到 `docker-compose.yml` 里有 `promiselink` / `postgres` / `redis` 服务，就以为"基础版应该 docker compose up"。

**真相**：基础版的核心交付物是 `pip install -e . + bash scripts/start.sh`（localhost:8000 源码运行）。
`docker-compose.yml` 的 `promiselink` 服务**仅用于生产部署 / 自托管 PoC**；PostgreSQL / Redis / Nginx 都在 `profiles: ["full"|"production"]` 后，默认 `docker compose up`（无 profile）只会启动 SQLite 模式。

**行动铁律**：
- 基础版所有 E2E / smoke test / 验证 → 本地 `.venv` 源码运行（`bash scripts/start.sh` 或 `uvicorn ...`）
- 基础版**禁止**部署到云端服务器（违反"数据从不出家门"数据主权承诺）
- 只有"全栈自托管场景"才用 `docker compose --profile full up`

### 教训 2：push tag ≠ 发布 release；deploy 链路只在 published release 上触发

**误判**：执行 `git tag v1.0.x && git push origin v1.0.x` 就以为"发布了"。

**真相**：
- `git push tag` 只把 tag 上传到 GitHub，**不创建 GitHub Release**。
- `build.yml` 的 `on: release: types: [published]` 事件**只在 Release 从 draft→published 时触发**。
- 之前 4 次 release 推送都没把工件 scp 到服务器 / 没改 download.html → 服务器 downloads/ 与 download.html 长期不一致（v0.9.9 错链指向磁盘上不存在的文件）。

**行动铁律**：
- 发布版本必须走：`gh release create vX.Y.Z --title ... --notes ...`（不是 `git push tag`）
- 发布后立即验证：`gh release view vX.Y.Z --json assets` 应包含 dmg/exe
- `build.yml` 触发后用 `gh run watch <run-id> --exit-status` 确认 deploy-to-server job 完成
- 服务器最终验证：`ssh ... ls -lht /opt/promiselink-pro/website/downloads/` 应有 vX.Y.Z 文件 + `grep -oE 'PromiseLink-[0-9][0-9.a-z-]*' download.html` 应匹配新版本

### 教训 3：服务器职责有边界，混用会污染数据主权

**服务器 47.116.219.15 的正确职责**（来自 PromiseLink-Pro `docs/postmortem/2026-07-12_基础版违规部署根因分析.md`）：

```
✅ 允许的部署
  ├── promiselink-pro        (专业版网关，0.0.0.0:8001)
  ├── promiselink-pro-postgres
  ├── promiselink-pro-redis
  ├── promiselink-nginx      (80/443)
  │    ├── /opt/promiselink-pro/website/ 官网静态文件
  │    └── /api/v1/pro/* → promiselink-pro
  └── promiselink-certbot    (Let's Encrypt ACME)

❌ 禁止的部署（数据主权原则）
  ├── promiselink-api 基础版容器  ← 2026-07-12 postmortem 已永久禁止
  └── 任何把"基础版用户数据"存云端的部署形态
```

**混合职责禁令**：基础版 `relay_client` 是**用户本地**的客户端，**不在服务器上**；它通过 HTTPS 调用专业版网关，**不要求服务器跑基础版服务端代码**。

### 教训 4：tag ↔ VERSION 必须一致；官网里"v0.9.9" / "v1.0.5" 这种历史错链，sed 必须能一并修

**误判**：
- (a) `git tag v1.0-rc1 && git push origin v1.0-rc1`，但 `VERSION=1.1.0`、`pyproject.toml=1.1.0`、`pyinstaller` 产物命名走 `VERSION` → release tag 是 `v1.0-rc1`、资产文件名是 `PromiseLink-1.1.0-...`，**命名学崩盘**。
- (b) `sed -i "s|...v${VERSION}...|..."` 只替换一个硬编码字符串，对 `v0.9.9` 这种老错链毫无办法 → **服务器 download.html 长期指 v0.9.9 而磁盘上 v0.9.9 已删**。

**真相**：
- tag 是给 `git` 看的；`build.yml` 上传的资产名是按 `VERSION` 文件走的；GitHub Release 页面只展示真实上传的资产；用户访问的是 `download.html`。
- **唯一权威**：`VERSION` 文件。tag 必须等于 VERSION（去掉可选的 `v` 前缀）。

**行动铁律（v1.1，2026-09-13 起）**：
- 发布前：`VERSION` 与 `pyproject.toml [project] version` 必须完全相等（手动 grep 校验）
- build.yml 入口门禁：release tag ≠ VERSION 直接 fail（`::error::` + exit 1），**不会触发 deploy**
- build.yml sed 改为正则 `[0-9a-zA-Z.\-]*` 匹配任意版本号，配合 `grep` 自检（必须能 grep 到新版本、必须不能 grep 到旧版本）
- 服务器巡检：`grep -oE 'PromiseLink-[0-9][0-9.a-z-]*' download.html | sort -u` 应只含新版本

---

## §1 基础版：本地源码运行标准流程

### 1.1 安装

```bash
git clone https://github.com/lulin70/PromiseLink && cd PromiseLink
git checkout vX.Y.Z          # 或 main
pip install -e '.[dev]'
cp .env.basic.example .env   # 编辑 .env 填 LLM_API_KEY（可选）
```

### 1.2 启动

```bash
bash scripts/start.sh        # 一键启动（推荐）
# 或：
python -m uvicorn promiselink.main:app --host 0.0.0.0 --port 8000
```

### 1.3 验证（无需 LLM）

```bash
pytest --co -q | tail -1     # 应显示 ~2035 tests collected
pytest tests/test_security_comprehensive.py -q --no-cov   # 50 项安全测试
```

### 1.4 何时**不**用 Docker

- ✅ E2E 真实用户测试 → 本地 .venv 源码运行（`httpx.AsyncClient` + `ASGITransport`）
- ✅ 全量回归测试 → 本地 .venv 源码运行
- ✅ release gates G1~G8 → 本地 .venv 源码运行
- ❌ "我以为是 staging"→基础版禁止云端 staging；只有"自托管 PoC"才允许 docker compose --profile full up 到本地服务器

---

## §2 官方服务器：47.116.219.15 的部署边界

### 2.1 容器职责矩阵

| 容器 | 端口 | 数据归属 | 谁可写 |
|---|---|---|---|
| promiselink-pro | 8001 → 8000 | 专业版用户数据（**不存基础版数据**） | 仅 Pro 部署流水线 |
| promiselink-pro-postgres | 5432（内网） | Pro 业务数据 | 仅 Pro 部署流水线 |
| promiselink-pro-redis | 6379（内网） | Pro 缓存 / jwt_blacklist | 仅 Pro 部署流水线 |
| promiselink-nginx | 80/443 | 官网静态文件 | Pro 部署 + 基础版 build.yml deploy-to-server |
| promiselink-certbot | 80/443 | ACME 证书 | Pro 部署流水线 |

### 2.2 官网静态文件结构（`/opt/promiselink-pro/website/`）

```
/opt/promiselink-pro/website/
├── index.html                  # 官网首页
├── download.html               # 下载页（README badge + 直接下载链接）
├── downloads/
│   ├── PromiseLink-X.Y.Z-mac.dmg
│   ├── PromiseLink-X.Y.Z-windows.exe
│   └── artifacts/               # CI 上传保留
└── ...（其他静态资产）
```

### 2.3 download.html 维护

| 维护动作 | 由谁 | 何时 |
|---|---|---|
| 推新版本后 sed 替换（**正则化 + 自检**，任何旧版本字符串都会改） | build.yml deploy-to-server（自动） | release published 后 |
| v0.9.9 / v1.0.5 这类历史错链兜底修复 | 人工 SSH + sed | 巡检发现 / 用户报修（**不应再发生**——见下方 v1.1 升级） |

**v1.1 自动化 sed 模式（build.yml 内，2026-09-13 升级）**：

```bash
# 1. 入口门禁：release tag 必须与 VERSION 文件一致
TAG_VERSION=${github.event.release.tag_name#v}
if [ "$(echo "$TAG_VERSION" | tr 'A-Z' 'a-z')" != "$(echo "$VERSION" | tr 'A-Z' 'a-z')" ]; then
  echo "::error::Release tag version ($TAG_VERSION) does not match VERSION ($VERSION)"
  exit 1
fi

# 2. 正则化重写（任意旧版本都会改；不再"该更新的没更新"）
sed -i -E \
  -e "s|PromiseLink-[0-9][0-9a-zA-Z.\\-]*-mac\\.dmg|PromiseLink-${VERSION}-mac.dmg|g" \
  -e "s|PromiseLink-[0-9][0-9a-zA-Z.\\-]*-windows\\.exe|PromiseLink-${VERSION}-windows.exe|g" \
  -e "s|约 82 MB · v[0-9][0-9a-zA-Z.\\-]*|约 82 MB · v${VERSION}|g" \
  -e "s|约 42 MB · v[0-9][0-9a-zA-Z.\\-]*|约 42 MB · v${VERSION}|g" \
  download.html

# 3. 自检：必须能 grep 到新版本，且不能再有旧版本残留
grep -q "PromiseLink-${VERSION}-mac.dmg" download.html || exit 1
grep -q "PromiseLink-${VERSION}-windows.exe" download.html || exit 1
STALE=$(grep -oE 'PromiseLink-[0-9][0-9a-zA-Z.\\-]*-(mac\.dmg|windows\.exe)' download.html | grep -v "PromiseLink-${VERSION}-" || true)
[ -z "$STALE" ] || { echo "stale: $STALE"; exit 1; }
```

**v1.0 已知缺陷（已被 v1.1 修复）**：旧 sed 模式只在 release published 触发；push tag 不触发；旧 sed 只替换一个硬编码字符串，无法修正 v0.9.9 → v1.0.5 这类历史错链——服务器 download.html 因此长期指 v0.9.9。**v1.1 之后这两类问题都不可能再发生**（门禁 fail-closed + 正则匹配任意旧版本）。

### 2.4 部署后强制校验（每次发布必跑）

```bash
SSH="ssh -i /Users/lin/trae_projects/PromiseLink-Pro/deploy/keys/promiselink.pem root@47.116.219.15"
$SSH 'ls -lht /opt/promiselink-pro/website/downloads/ | head -3'
# 期望：新版本 dmg/exe 在前两行

$SSH 'grep -oE "PromiseLink-[0-9][0-9.a-z-]*" /opt/promiselink-pro/website/download.html | sort -u'
# 期望：仅含新版本文件名
```

---

## §3 GitHub Release 发布标准流程

### 3.1 三种"发布"的区别

| 动作 | 触发 build.yml？ | 在 Releases 页可见？ | deploy 链路是否启动？ |
|---|---|---|---|
| `git push origin vX.Y.Z` | ❌ | ❌（仅 tag 页） | ❌ |
| `gh release create vX.Y.Z --draft` | ❌ | ✅ draft | ❌ |
| `gh release create vX.Y.Z`（**默认 published**） | ✅ | ✅ published | ✅ |
| `gh release edit vX.Y.Z --draft=false`（draft → published） | ✅ | ✅ published | ✅ |

### 3.2 强制流程（用户规则 3：发布前模拟真实用户测试 → 发布）

1. **本地验证**（本机 .venv）
   ```bash
   pytest tests/ -q --no-cov --ignore=tests/test_e2e_real_user_scenarios.py
   bash scripts/start.sh &
   sleep 5 && curl -sf http://localhost:8000/api/v1/health
   kill %1
   ```

2. **本机真实 HTTP smoke test**（而非 ASGITransport in-process）
   - 启动服务 → curl /docs /openapi.json 真实 HTTP → 关闭服务

3. **创建 GitHub Release（published，非 draft）**
   ```bash
   gh release create vX.Y.Z \
     --title "PromiseLink vX.Y.Z — <feature>" \
     --notes "$(cat <<'EOF'
   ## <feature summary>

   ### 验证证据
   - ...
   EOF
   )" \
     --target main
   ```

4. **监控 build.yml**
   ```bash
   gh run watch <run-id> --exit-status
   ```
   期望：build-macos ✅ + build-windows ✅ + deploy-to-server ✅

5. **服务器最终校验**（§2.4 强制命令）

6. **更新文档**：`tracker` 写入 commit / tag / release URL / deploy 时间戳

### 3.3 反模式（禁止）

- ❌ `git push origin vX.Y.Z` 当作"发布"（不会触发 deploy）
- ❌ `gh release create --draft` 然后忘记 publish
- ❌ "我手动 scp 一下就行" → 失去审计链
- ❌ 把 release notes 留空（用户看不到验证证据）

---

## §4 桥接中继（relay client / server）维护

### 4.1 架构

```
[用户本地基础版]  ──── HTTPS ────>  [专业版网关 promiselink-pro :8001]
   relay_client                       专业版 API / LLM 增强
   (用户本地代码)                       (服务器侧)
```

### 4.2 维护要点

| 项 | 位置 | 维护责任 |
|---|---|---|
| `relay_client` 实现 | 基础版 `src/promiselink/` | 基础版代码（不涉及服务器变更） |
| `promiselink-pro` 网关 | 服务器 :8001 | Pro 部署流水线 |
| `promiselink-pro` 的 `/api/v1/pro/*` 路由 | 服务器 | Pro 部署流水线 |
| `download.html` 中"POC_SECRET"链接 | 服务器静态文件 | Pro 部署流水线 |

### 4.3 W5 release 不改桥接

W5 是基础版本地功能（实体归一 + candidate token），**不依赖**专业版网关。bridge 中继不需要因 W5 更新。

---

## §5 发布前清单（Pre-release checklist）

> **强制**：以下每项必须勾选才能 `gh release create`；任意一项缺失即阻塞。

### 5.1 代码质量

- [ ] `pytest tests/ -q --no-cov --ignore=tests/test_e2e_real_user_scenarios.py` 通过
- [ ] `mypy src/` 0 错误
- [ ] `ruff check src/ tests/ scripts/` 0 错误
- [ ] `gitleaks detect` 0 命中

### 5.2 release gates（W5 当前阶段）

- [ ] G1 W5 E2E 14/14 PASS（`scripts/e2e/e2e_w5_real_user.py`）
- [ ] G2 W4 baseline 真实存在（`docs/evidence/w4_baseline.json` schema_version=w4-baseline-v1）
- [ ] G3 Anti-ghost 真实激活（`scripts/quality/check_w5_antighost.py`）
- [ ] G4 Migration parity（同 §5.2.1 manifest）
- [ ] G5 Manifest v1 validator 接受
- [ ] G6 全仓回归 0 failed
- [ ] G7 Rollback 演练
- [ ] G8 Secret 轮换演练

### 5.3 真实用户验证（用户规则 3）

- [ ] 本机 `.venv` 起服务 → 真实 HTTP `curl http://localhost:8000/api/v1/health`
- [ ] 浏览器打开 `http://localhost:8000` → 走通核心闭环（录入事件 → 实体提取 → Todo 生成 → 关联发现）
- [ ] `docs` Swagger UI 可访问

### 5.4 文档与追踪

- [ ] `tracker` 更新到最新版本（含本次 commit / release / 验证证据）
- [ ] `CHANGELOG.md` 描述本次变更
- [ ] `PROJECT_STATUS.md` 仪表盘进度同步

### 5.5 服务器/官网（仅 release 阶段）

- [ ] `gh release create` 默认 published（非 draft）
- [ ] `gh run watch <run-id>` ✅
- [ ] SSH 校验 §2.4 两条命令

---

## §6 故障排查速查

| 现象 | 根因 | 修复 |
|---|---|---|
| 服务器 download.html 仍指 v0.9.9 | push tag 不触发 deploy | 手工 SSH + sed §2.3 兜底；下次用 `gh release create`（非 `git push tag`） |
| Release published 但服务器 downloads/ 无新文件 | build.yml deploy job 失败 | `gh run watch` 看 logs；检查 `secrets.SERVER_SSH_KEY` / `secrets.SERVER_HOST` 是否仍有效 |
| 本机 E2E 通过但服务器 502 | 数据迁移未跑 | SSH 进容器 `alembic upgrade head` |
| `docker compose --profile full up` 报端口冲突 | 5432/6379/8000 被占 | 改用本地 `.venv` 源码运行（基础版主路径） |
| `pip install -e .` 报依赖缺失 | venv 未激活 | `source .venv/bin/activate` 后重试 |

---

## §7 引用

- 项目状态：[docs/PROJECT_STATUS.md](../PROJECT_STATUS.md)
- 部署剧本（Stage 0）：[W5_STAGE0_STAGING_DEPLOY_v1.md](W5_STAGE0_STAGING_DEPLOY_v1.md)
- 阻塞项 tracker：[../design/W5_IMPLEMENTATION_BLOCKERS_TRACKING_v1.md](../design/W5_IMPLEMENTATION_BLOCKERS_TRACKING_v1.md)
- Postmortem（基础版禁云端）：[../../PromiseLink-Pro/docs/postmortem/2026-07-12_基础版违规部署根因分析.md](../../PromiseLink-Pro/docs/postmortem/2026-07-12_基础版违规部署根因分析.md)
- build.yml：`.github/workflows/build.yml`
- 服务器 deploy job 触发点：`on: release: types: [published]`
