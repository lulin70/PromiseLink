# PromiseLink MPL 2.0 边界法律确认

> **文档版本**: v2.0
> **日期**: 2026-07-09
> **状态**: 技术团队评估，待法律顾问正式确认
> **关联文档**: `docs/architecture/Repo_Split_Decision.md` §7、`docs/architecture/edition_architecture.md`、`LICENSE`、`docs/legal/PRO_LICENSE_AGREEMENT.md`
> **变更说明**: 本文档替代原 `AGPL_BOUNDARY.md`（v1.0, 2026-06-18）。基础版许可证已从 GNU AGPL v3 迁移至 Mozilla Public License 2.0（MPL 2.0），详见第 8 章。

---

## 1. 文档目的

本文档明确 PromiseLink 项目中 MPL 2.0 许可证的传染边界（copyleft boundary），定义基础版与专业版之间的法律隔离机制，确保：

1. 基础版（PromiseLink）的 MPL 2.0 开源义务得到完整履行
2. 专业版（PromiseLink-Pro）的商业闭源模式不受 MPL 2.0 传染
3. 用户、开发者、商业合作伙伴清晰理解各自的权利与义务
4. 明确 MPL 2.0 相比 AGPL v3 在网络服务场景下的优势

> ⚠️ **免责声明**：本文档为技术团队基于对 MPL 2.0 的理解所做的评估，**不构成法律意见**。MPL 2.0 的部分条款在法律实践中存在解释空间，正式发布前建议由具备开源协议经验的执业律师出具书面法律意见。

---

## 2. 许可证架构

### 2.1 双版本许可体系

| 版本 | 仓库 | 许可证 | 传染性 | 商业模式 |
|------|------|--------|--------|----------|
| **基础版**（PromiseLink） | `lulin70/PromiseLink`（公开） | Mozilla Public License 2.0 | 弱 copyleft，文件级隔离 | 开源免费 |
| **专业版**（PromiseLink-Pro） | `lulin70/PromiseLink-Pro`（私有） | 私有商业许可 | 不受 MPL 约束 | 订阅付费 |
| **小程序前端**（PromiseLink-miniapp） | `lulin70/PromiseLink-miniapp`（私有） | 私有商业许可 | 不受 MPL 约束 | 随专业版分发 |
| **协议层**（promiselink-contracts） | 公开 | MIT License | 不传染 | 开源免费 |
| **工具层**（promiselink-utils） | 公开 | MIT License | 不传染 | 开源免费 |

### 2.2 物理隔离原则

基础版与专业版采用**物理隔离**（分仓库），而非单仓库多分支：

- 基础版仓库：包含完整的 13 步管线、实体提取、记忆、Todo、Promise、关联发现、Docker、H5、适配器
- 专业版仓库：包含网关、小程序、语音云端、图谱融合、定制版功能
- 两仓库之间通过 HTTP API 通信，无源码级依赖（非 submodule）
- 专业版通过 `pip install` 引入基础版发布的包，**不修改**任何基础版源码

---

## 3. MPL 2.0 核心特性

### 3.1 文件级 copyleft（关键特性）

MPL 2.0 采用**文件级**（file-level）copyleft，这是其与 GPL/AGPL 系列**库级/作品级** copyleft 的本质区别：

| 维度 | MPL 2.0 | GPL v3 | AGPL v3 |
|------|---------|--------|---------|
| Copyleft 范围 | 单个文件 | 整个衍生作品 | 整个衍生作品 + 网络交互 |
| 修改后开源义务 | 仅修改过的 MPL 文件需开源 | 整个作品需开源 | 整个作品需开源 + 网络服务也触发 |
| 与闭源代码混合 | 允许（Larger Work） | 不允许 | 不允许 |
| 网络服务触发 | **不触发** | 不触发 | **触发**（第 13 条） |

**MPL 2.0 第 3.3 条（Larger Work）原文要点**：

> You may create and distribute a Larger Work under terms of Your choice, provided that You also comply with the requirements of this License for the Covered Software.

即：你可以将 MPL 文件与闭源文件组合成一个 Larger Work（更大作品），整个 Larger Work 可以采用你自定义的条款，只要 MPL 文件本身仍然保持 MPL 许可。

### 3.2 无远程网络交互条款

MPL 2.0 **没有**类似 AGPL v3 第 13 条的"远程网络交互"条款。这是 PromiseLink 选择 MPL 2.0 的核心原因：

- **AGPL v3 第 13 条**：修改后通过网络提供服务也触发开源义务（即使不分发）
- **MPL 2.0**：无此条款。修改后通过网络提供服务，只需开源修改过的 MPL 文件本身，不触发其他文件的开源义务

### 3.3 与 GPL/AGPL 的兼容性

MPL 2.0 通过 **Secondary License** 机制（第 1.12 条、第 3.3 条）与 GPL 系列兼容：

- 如果项目希望在 MPL 2.0 之外同时允许以 GPL 分发，可在文件头声明 "Incompatible With Secondary Licenses" 为否
- PromiseLink 基础版**未**声明 Incompatible With Secondary Licenses，因此默认允许与 GPL 系列组合分发

---

## 4. 传染边界定义

### 4.1 MPL 2.0 传染触发条件

根据 MPL 2.0 第 3.1 条（Distribution of Source Form）和第 3.2 条（Distribution of Executable Form），传染性触发条件如下：

| 触发条件 | 是否传染 | 说明 |
|----------|----------|------|
| 修改 MPL 2.0 源码文件并分发 | ✅ 传染（仅该文件） | 修改过的文件必须继续以 MPL 2.0 开源 |
| 修改 MPL 2.0 源码文件并通过网络提供服务 | ❌ **不传染** | MPL 2.0 无网络交互条款，修改后提供服务不触发额外义务（分发时仍需开源该文件） |
| 将 MPL 2.0 文件与闭源文件组合成 Larger Work | ❌ 不传染（闭源部分） | 闭源文件保持闭源，仅 MPL 文件需开源 |
| 静态链接 MPL 2.0 代码 | ⚠️ 视情况 | 若构成"修改 MPL 文件"则该文件需开源；若仅作为库调用则不传染 |
| 通过 import 调用 MPL 2.0 模块 | ❌ 不传染 | import 不构成"修改文件"，被调用模块保持 MPL，调用方不受传染 |
| 独立进程通过管道/命令行调用 MPL 2.0 程序 | ❌ 不传染 | 独立程序间通信不构成"修改" |
| 通过网络 API 调用 MPL 2.0 服务 | ❌ 不传染 | 网络通信不构成"修改"，也不触发网络条款 |
| 仅运行未修改的 MPL 2.0 程序 | ❌ 不传染 | 未修改 + 未分发，不触发 copyleft |
| 分发未修改的 MPL 2.0 程序 | ❌ 不传染（需保留声明） | 需保留原始许可声明，但无需额外开源 |

### 4.2 Mozilla 基金会对 MPL 2.0 的官方解释

根据 Mozilla 基金会对 MPL 2.0 的官方 FAQ：

> **MPL 2.0 FAQ 核心要点**：
> - MPL 是一个弱 copyleft 许可证，copyleft 范围限定在**文件级**
> - 修改过的文件必须以 MPL 开源，但新文件可以采用任何许可证（包括闭源）
> - 通过 API 调用 MPL 代码不触发 copyleft
> - MPL 2.0 没有 AGPL v3 第 13 条的网络服务条款

**参考来源**：
- MPL 2.0 全文: https://www.mozilla.org/media/MPL/2.0/index.txt
- MPL 2.0 FAQ: https://www.mozilla.org/en-US/MPL/2.0/FAQ/
- Mozilla 许可证政策: https://www.mozilla.org/en-US/MPL/

### 4.3 PromiseLink 的传染边界判定

基于上述规则，PromiseLink 各集成场景的传染性判定：

| 集成场景 | 技术方式 | 是否触发传染 | 分析依据 |
|----------|----------|------------|----------|
| **专业版通过 import 依赖基础版代码**（主要场景） | Python import，117 处跨 30 文件 | ❌ 不传染 | import 不构成"修改文件"，MPL §3.3 Larger Work 允许 MPL 文件与闭源文件组合 |
| **专业版通过 pip install 引入基础版** | 包依赖 | ❌ 不传染 | 同上，import 调用不构成"修改文件"，基础版文件保持 MPL，专业版文件不受传染 |
| **专业版网关通过 WSS 调用基础版 relay_client** | 网络通信 | ❌ 不传染 | relay_client（基础版 MPL 文件）与网关（专业版私有）通过 WebSocket 通信，不修改文件 |
| **用户修改基础版 MPL 文件并自用** | 源码修改 | ❌ 不触发开源 | MPL 无网络条款，自用不分发则无义务 |
| **用户修改基础版 MPL 文件并分发** | 源码修改 + 分发 | ✅ 需开源修改文件 | 修改过的 MPL 文件必须继续以 MPL 开源，但用户新增文件不受传染 |
| **用户修改基础版 MPL 文件并通过网络提供服务** | 源码修改 + 网络服务 | ❌ 不触发额外义务 | MPL 无网络条款，仅分发时需开源修改过的文件 |

> **架构事实说明**：专业版（PromiseLink-Pro）从基础版（PromiseLink）直接 import 了 **117 处代码**，覆盖 8 个核心模块：`promiselink.models`（32 处，共享 ORM 模型）、`promiselink.core`（31 处，共享认证/日志）、`promiselink.database`（15 处，共享数据库会话）、`promiselink.services`（12 处，共享 LLM 客户端）、`promiselink.config`（11 处，共享配置）、`promiselink.api`（7 处，共享中间件/Schemas）、`promiselink.main`（8 处，共享 FastAPI app）。这是"同一个单体应用的两个文件夹"架构，不是微服务调 API。但 MPL 2.0 的 Larger Work 条款天然允许这种 import + Proprietary 组合，无需改为 HTTP API。

---

## 5. import 依赖不构成"衍生作品"的法律分析

### 5.1 import 依赖的隔离原理

PromiseLink 专业版通过 Python `import` 直接引用基础版代码（117 处跨 30 文件），这种"import 依赖"关系不触发 MPL copyleft，理由如下：

1. **文件级隔离**（核心）：MPL 2.0 的 copyleft 限定在**文件级**。专业版的 `.py` 文件是独立的新文件，不修改任何基础版 MPL 文件，因此专业版文件不受 MPL 传染。这是 MPL 2.0 与 GPL/AGPL 的本质区别 — GPL/AGPL 的 copyleft 作用于"组合作品"级，而 MPL 2.0 仅作用于"文件"级。

2. **Larger Work 条款**：MPL 2.0 第 3.3 条明确允许将 MPL 代码与闭源代码组合成 Larger Work：
   > "You may create and distribute a Larger Work under terms of Your choice, provided that You also comply with the requirements of this License for the Covered Software."

   即：专业版可以 freely import 基础版的任何代码，整个专业版作为 Larger Work 可以保持 Proprietary，只需基础版的 MPL 文件本身保持 MPL 许可。

3. **import 不等于修改**：Python 的 `import` 语句调用模块，不修改源文件内容。被 import 的基础版文件仍然是原始的 MPL 许可文件，专业版只是"使用"而非"修改"它们。

4. **共享 ORM/数据库/认证的合法性**：专业版 import 基础版的 `models`（ORM 模型）、`database`（数据库会话）、`core`（认证中间件）等模块，这是"同一个单体应用的两个文件夹"架构。MPL 2.0 天然允许这种深度耦合 — 只要专业版的新文件不修改基础版 MPL 文件的内容，专业版文件就可以保持 Proprietary。

5. **与 AGPL 方案的关键差异**：
   - **AGPL 方案**：import 基础版代码后，整个专业版可能被视为"衍生作品"，需要双授权机制才能保持 Proprietary
   - **MPL 2.0 方案**：import 基础版代码后，只有基础版的原文件保持 MPL，专业版的新文件天然可以保持 Proprietary，**不需要任何额外机制**

6. **类比先例**：此模式类似于：
   - Firefox（MPL 2.0）的闭源组件与 MPL 组件共存于同一应用
   - Thunderbird（MPL 2.0）的闭源插件 import MPL 核心
   这些场景中，Mozilla 和开源社区均认可文件级隔离的 copyleft 边界。

### 5.2 专业版 import 基础版代码的架构图

```
┌─────────────────────────────────────────────────────────────┐
│  专业版（PromiseLink-Pro，Proprietary）                      │
│                                                             │
│  专业版新文件（Proprietary，不受 MPL 约束）：                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  pro_api/     │  │  pro_services/│  │  pro_models/ │      │
│  │  (voice.py)   │  │  (asr/tts)   │  │  (voice_     │      │
│  │  (media.py)   │  │  (nlg/nlu)   │  │   session)   │      │
│  │  (email_sync) │  │  (ocr)       │  │              │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                 │               │
│         │    import 117 处（不修改基础版文件）               │
│         │                 │                 │               │
└─────────┼─────────────────┼─────────────────┼──────────────┘
          │                 │                 │
══════════╪═════════════════╪═════════════════╪═════════════
          │ MPL 2.0 传染边界（文件级隔离，Larger Work 允许）  │
══════════╪═════════════════╪═════════════════╪═════════════
          │                 │                 │
┌─────────▼─────────────────▼─────────────────▼──────────────┐
│  基础版（PromiseLink，MPL 2.0）                              │
│                                                             │
│  基础版 MPL 文件（保持 MPL 2.0，专业版不修改）：             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  models/      │  │  core/        │  │  database/   │      │
│  │  (ORM 模型)   │  │  (认证/日志)  │  │  (会话工厂)  │      │
│  │  32 处被import│  │  31 处被import│  │  15 处被import│      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  services/    │  │  config/      │  │  api/        │      │
│  │  (LLM 客户端) │  │  (配置)       │  │  (中间件)    │      │
│  │  12 处被import│  │  11 处被import│  │  7 处被import │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

**结论**：专业版通过 import 依赖基础版代码（117 处），但专业版的新文件不修改任何基础版 MPL 文件。依据 MPL 2.0 §3.3 Larger Work 条款，专业版作为 Larger Work 可保持 Proprietary，仅基础版的 MPL 文件保持 MPL 2.0 许可。**不需要改为 HTTP API 架构，也不需要双授权机制。**

### 5.3 pip install 依赖的声明

专业版通过 `pyproject.toml` 声明依赖 `promiselink @ git+https://github.com/lulin70/PromiseLink.git@main`，这种依赖关系不触发传染：

- **import 不等于修改**：Python 的 `import` 语句调用模块，不修改源文件内容
- **Larger Work 允许**：MPL 2.0 第 3.3 条明确允许将 MPL 代码与闭源代码组合成 Larger Work
- **专业版文件保持闭源**：专业版的 `.py` 文件是独立文件，不因 import 基础版而变成 MPL
- **基础版文件保持 MPL**：被 import 的基础版文件仍然是 MPL 许可，专业版分发时需包含基础版的 MPL 文件和许可声明（通过 NOTICE 文件声明，见第 7 章）

---

## 6. 用户使用基础版的开源义务

### 6.1 用户修改基础版后的义务

任何用户修改 PromiseLink 基础版源码后，需遵守 MPL 2.0 的以下义务：

| 使用方式 | 开源义务 | 适用条款 |
|----------|----------|----------|
| 修改后仅本地自用，不联网 | 无需开源 | MPL 2.0 不限制使用 |
| 修改后通过网络对外提供服务 | **无需开源** | MPL 2.0 无网络交互条款（与 AGPL v3 的关键区别） |
| 修改后分发给他人 | **必须开源**修改过的文件 | MPL 2.0 第 3.1 条 |
| 修改后与其他代码组合分发 | 仅修改过的 MPL 文件需开源 | MPL 2.0 第 3.3 条（Larger Work） |
| 未修改，仅运行 | 无需开源 | MPL 2.0 不限制运行 |
| 未修改，分发给他人 | 无需开源（需保留声明） | 需保留原始许可声明和版权信息 |

### 6.2 开源义务的具体要求

若用户修改基础版文件并分发，必须：

1. **提供修改过的源代码**：仅修改过的 MPL 文件需要开源，新增文件可采用任意许可证（包括闭源）。
2. **保留 MPL 2.0 许可证**：修改过的文件必须继续以 MPL 2.0 许可，不得更改许可证。
3. **保留版权声明**：保留原始版权声明和作者信息。
4. **声明修改内容**：在源代码中注明修改日期和修改内容（MPL 2.0 第 3.4 条）。
5. **提供 MPL 2.0 许可证副本**：分发时需告知接收方本文件受 MPL 2.0 约束，并提供获取许可证的途径。

### 6.3 商业用户建议

- **如需闭源使用**：可直接修改基础版新增闭源文件（MPL 允许 Larger Work），但修改过的 MPL 文件仍需开源。如需完全闭源，建议购买专业版商业许可。
- **如需定制功能**：推荐在新增文件中实现定制逻辑，避免修改基础版 MPL 文件，这样定制功能可保持闭源。
- **如需修改基础版 MPL 文件**：修改过的文件必须按 MPL 2.0 开源，建议将修改贡献回上游（Pull Request），惠及社区。

---

## 7. 风险缓解措施

### 7.1 技术隔离措施

1. **物理分仓库**：基础版与专业版分属不同 Git 仓库，无 submodule 依赖。
2. **文件级隔离**（核心）：专业版的新文件（`pro_api/`、`pro_services/`、`pro_models/` 等）是独立的 `.py` 文件，不修改任何基础版 MPL 文件。专业版通过 import 引用基础版代码（117 处），但 import 不构成"修改"。
3. **不修改原则**：专业版通过 pip install 引入基础版，不修改任何基础版源码文件。所有定制功能在专业版仓库的新文件中实现。
4. **NOTICE 声明**：专业版仓库包含 NOTICE 文件，声明使用了 MPL 2.0 的基础版组件（满足 MPL §3.4 通知要求）。
5. **新增文件原则**：专业版的定制功能在专业版仓库的新文件中实现，不触碰基础版 MPL 文件。

### 7.2 法律审查清单

正式发布前，建议完成以下法律审查（由执业律师出具书面意见）：

- [ ] import 依赖 + Larger Work 条款是否完全不触发 MPL 2.0 传染（117 处 import 的合法性确认）
- [ ] MPL 2.0 第 3.3 条 Larger Work 条款对专业版商业模式的适用性确认
- [ ] 共享 ORM/数据库/认证中间件的深度耦合是否影响 Larger Work 判定
- [ ] 商业 License 与 MPL 2.0 的兼容性声明
- [ ] 用户修改基础版后通过 SaaS 提供服务的义务告知文案（MPL 下此场景无需开源，但需明确告知）
- [ ] MPL 2.0 的专利授权条款（第 2.1(b) 条）对商业用户的影响评估

### 7.3 与 AGPL v3 相比的风险降低

相比原 AGPL v3 方案，MPL 2.0 显著降低了以下风险：

| 风险项 | AGPL v3 | MPL 2.0 |
|--------|---------|---------|
| 网络服务触发开源义务 | ✅ 第 13 条触发 | ❌ 无此条款 |
| 修改后整个作品传染 | ✅ 强 copyleft | ❌ 文件级隔离 |
| 与闭源代码混合 | ❌ 不允许 | ✅ Larger Work 允许 |
| 法律争议性 | 高（第 13 条解释争议） | 低（Mozilla 基金会明确 FAQ） |
| 商业用户接受度 | 低（企业规避 AGPL） | 高（MPL 被广泛接受） |

### 7.4 失去 SaaS 保护的代价与风险评估

MPL 2.0 相比 AGPL v3 的**唯一实质代价**是失去基础版的 SaaS 保护（网络服务条款）。本节评估此代价的实际影响。

#### 7.4.1 基础版的独立运行能力

**基础版（PromiseLink）可以完全独立运行**，不依赖 Pro 的任何代码：

- 用户配置 `LLM_API_KEY`（支持 `moka_ai` / `openai` / `anthropic` 三种 Provider）即可启动
- 提供完整的 13 步 AI 管线：事件录入 → 实体提取 → 人脉/关系/待办/承诺分析
- 包含 Docker 一键安装、H5 宽屏前端、SQLite 存储、PIPL/GDPR 隐私合规
- 基础版 `src/` 中无任何对 Pro 代码的依赖（仅 2 处注释说明哪些功能已迁移到 Pro）

#### 7.4.2 基础版与 Pro 的能力对比

| 能力 | 基础版（独立运行） | Pro 增量 |
|------|-------------------|----------|
| 事件录入 → AI 解析 → 人脉/关系/待办/承诺 | ✅ 完整 13 步管线 | — |
| LLM 接入 | ✅ 用户自配 API Key | 网关中继（用户无需配 Key） |
| H5 前端 | ✅ 宽屏两栏布局 | 微信小程序（手机竖屏） |
| Docker 一键安装 | ✅ | + License 激活 + 计费 |
| 语音输入/输出（ASR/TTS） | ❌ | ✅ |
| 图片扫描 OCR（名片识别） | ❌ | ✅ |
| 邮件同步 | ❌ | ✅ |
| 微信转发粘贴解析 | ❌ | ✅ |
| CSV 批量导入 | ❌ | ✅ |
| 种子用户邀请机制 | ❌ | ✅ |

#### 7.4.3 竞品 fork 基础版做 SaaS 的可行性分析

| 维度 | 分析 |
|------|------|
| **技术上可行吗？** | ✅ 可行 — 基础版可独立运行，竞品 fork 后配 LLM API Key 即可启动 SaaS |
| **竞品需要自己解决什么？** | LLM 接入成本、用户管理、计费系统、运维监控、客服支持 |
| **MPL 2.0 下竞品的义务** | 修改基础版 MPL 文件后**分发**需开源修改的文件；但**网络服务不触发**开源（与 AGPL 的关键区别） |
| **竞品能获得 Pro 的能力吗？** | ❌ 不能 — 语音/OCR/小程序/License/网关等核心差异化功能在 Pro 仓库，不开源 |

#### 7.4.4 风险评估结论

| 风险项 | 等级 | 说明 |
|--------|------|------|
| 竞品 fork 基础版做 SaaS | **中** | 基础版可独立运行，技术上可行；但竞品需自建 LLM 接入/用户管理/计费等基础设施 |
| 竞品威胁 Pro 商业模式 | **低** | Pro 的语音/OCR/小程序/License/网关等核心差异化功能不开源，竞品无法获得 |
| 基础版社区生态受损 | **低** | MPL 2.0 比 AGPL 更受企业接受，有利于社区推广 |
| 整体商业风险 | **可接受** | 商业壁垒在 Pro 而非基础版；基础版开源是为了社区建设和生态推广 |

> **结论**：失去 SaaS 保护是 MPL 2.0 的唯一代价，但风险可接受。基础版可以独立运行，竞品 fork 做 SaaS 技术上可行，但竞品需要自建 LLM 接入/用户管理/计费等基础设施，且无法获得 Pro 的核心差异化功能。真正的商业壁垒在 Pro（语音/OCR/小程序/License/网关），Pro 保持 Proprietary 不开源。

---

## 8. 从 AGPL v3 迁移到 MPL 2.0 的变更说明

### 8.1 迁移背景

PromiseLink 基础版原采用 GNU AGPL v3，但由于以下原因迁移至 MPL 2.0：

1. **AGPL v3 第 13 条的传染风险**：专业版通过 import 依赖基础版代码（117 处），AGPL v3 的强 copyleft 可能将整个专业版视为"衍生作品"，需要双授权机制才能保持 Proprietary。商业用户普遍规避 AGPL。
2. **商业用户接受度**：AGPL v3 被许多企业列入"禁止使用"清单，阻碍基础版的推广。
3. **MPL 2.0 的明确性**：MPL 2.0 的文件级 copyleft 和无网络条款特性，使传染边界清晰，降低法律不确定性。
4. **Mozilla 基金会的良好治理**：MPL 2.0 由 Mozilla 基金会维护，有完善的 FAQ 和实践案例。

### 8.2 迁移的合法性

本次许可证迁移的合法性依据：

1. **版权持有人同意**：PromiseLink 基础版的版权持有人（lulin70）有权更改许可证。所有现有贡献者需被通知并同意（PromiseLink 目前为单人项目，无第三方贡献者）。
2. **AGPL v3 允许更改**：AGPL v3 第 13 条允许版权持有人以其他许可证分发（双许可）。从 AGPL v3 迁移到 MPL 2.0 是版权持有人主动选择，不违反 AGPL v3。
3. **历史版本保留**：仓库 git history 中的历史版本仍保持 AGPL v3 许可，迁移仅对当前及未来版本生效。
4. **CLA 声明**：PromiseLink 的 CLA（Contributor License Agreement）已约定贡献者授予版权持有人更改许可证的权利。

### 8.3 迁移的影响

| 影响项 | 迁移前（AGPL v3） | 迁移后（MPL 2.0） |
|--------|-------------------|-------------------|
| 修改后网络服务 | 必须开源整个作品 | 无需开源（仅分发时需开源修改过的文件） |
| 与专业版混合 | 需谨慎避免传染 | 允许 Larger Work 组合 |
| 商业用户接受度 | 低 | 高 |
| 传染边界清晰度 | 存在争议 | 明确（文件级） |
| 社区贡献门槛 | 高（贡献者担心 AGPL） | 适中 |

### 8.4 已完成的迁移工作

- [x] `LICENSE` 文件替换为 MPL 2.0 官方全文
- [x] `README.md` / `README.en.md` / `README.jp.md` 三语 README 许可证声明更新
- [x] `pyproject.toml` 许可证字段更新
- [x] 代码文件头部许可声明更新
- [x] 本文档（替代原 `AGPL_BOUNDARY.md`）
- [x] `CONTRIBUTING.md` 和 `CLA.md` 更新
- [x] `CHANGELOG.md` 记录许可证迁移

---

## 9. 结论

1. **基础版（PromiseLink）**：采用 MPL 2.0，文件级 copyleft，修改过的文件需开源，但无网络服务触发条款。
2. **专业版（PromiseLink-Pro）**：采用私有商业许可，通过 HTTP API 调用基础版，不修改任何 MPL 文件，不受 MPL 约束。
3. **桥接接口**：API 桥接（HTTP 通信）+ pip import 不触发 MPL 2.0 传染，文件级隔离 + 进程隔离双重保障。
4. **Larger Work**：MPL 2.0 第 3.3 条明确允许 MPL 文件与闭源文件组合，专业版可安全闭源。
5. **用户义务**：用户修改基础版文件后**分发**时需开源修改过的文件；仅本地使用或网络服务**不触发**开源义务。
6. **迁移合法性**：从 AGPL v3 迁移到 MPL 2.0 由版权持有人主动选择，合法合规。

> ⚠️ **再次声明**：本结论为技术团队的评估，建议正式发布前由具备开源协议经验的执业律师出具书面法律意见。本团队不对本文档的准确性承担法律责任。

---

## 参考资料

1. Mozilla Public License 2.0 全文: https://www.mozilla.org/media/MPL/2.0/index.txt
2. MPL 2.0 FAQ: https://www.mozilla.org/en-US/MPL/2.0/FAQ/
3. Mozilla 许可证政策: https://www.mozilla.org/en-US/MPL/
4. GNU AGPL v3 全文（历史参考）: https://www.gnu.org/licenses/agpl-3.0.html
5. FSF GPL FAQ（历史参考）: https://www.gnu.org/licenses/gpl-faq.html
6. PromiseLink 仓库拆分决策: `docs/architecture/Repo_Split_Decision.md`
7. PromiseLink 版本架构: `docs/architecture/edition_architecture.md`
8. PromiseLink API 设计: `docs/design/API_Design_v1.md`
9. PromiseLink 专业版商业许可协议: `docs/legal/PRO_LICENSE_AGREEMENT.md`
10. PromiseLink 服务条款: `docs/legal/TERMS_OF_SERVICE.md`
