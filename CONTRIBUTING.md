# 贡献指南 — PromiseLink

> 感谢你对 PromiseLink 的关注！本文档说明如何参与贡献。

## 1. 许可证声明

PromiseLink 采用 **AGPL v3** 开源许可证。提交贡献即表示你同意：

- 你的贡献代码将同样以 AGPL v3 许可发布
- 你授予 PromiseLink 项目团队使用、修改、再许可你贡献代码的权利
- 你确认你拥有贡献代码的版权或有权以 AGPL v3 许可发布

**禁止行为：**
- ❌ 不得通过 PR 修改 LICENSE 文件或许可证声明
- ❌ 不得在贡献中移除 "via PromiseLink" 品牌标识
- ❌ 不得移除 `X-Powered-By: PromiseLink` 响应头
- ❌ 不得移除启动日志中的 AGPL v3 许可证声明

## 2. CLA 贡献者许可协议

为保证项目的法律清晰度与可持续运营，PromiseLink 要求所有外部贡献者在首次提交 Pull Request 时签署 **贡献者许可协议（CLA）**。完整协议文本见 [.github/CLA.md](.github/CLA.md)。

### 2.1 谁需要签署 CLA

- **必须签署**：所有通过 Pull Request 向 PromiseLink 提交代码、文档或设计贡献的外部贡献者。
- **无需签署**：项目核心维护者（已在 `allowList` 中配置，如 `lulin70`）。

### 2.2 CLA 签署流程

CLA 签署通过 **CLA Assistant** 自动化完成，流程如下：

1. 你首次向 PromiseLink 提交 Pull Request。
2. CLA Assistant 自动检查你的 GitHub 账户是否已签署 CLA。
3. 若未签署，CLA Assistant 会在 PR 中留下评论，附带签署链接。
4. 点击链接，阅读 [.github/CLA.md](.github/CLA.md) 协议文本，确认签署信息（GitHub 用户名、真实姓名、邮箱）。
5. 完成电子签署后，CLA Assistant 自动更新 PR 状态，添加 `cla: yes` 标签。
6. PR 通过 CLA 检查后，方可进入代码审查流程。

**一次签署，长期有效**：同一 GitHub 账户只需签署一次，后续所有 PR 自动通过 CLA 检查，无需重复签署。

### 2.3 CLA 检查规则

- CLA Assistant 配置文件位于 [.github/cla-assistant.json](.github/cla-assistant.json)。
- 当 PR 贡献行数超过 `threshold`（默认 5 行）时触发 CLA 检查。
- PR 必须带有 `cla: yes` 标签才会被合并（`requireLabel: cla: yes`）。
- 未签署 CLA 的 PR 将被标记为 `cla: no` 并阻止合并。

### 2.4 CLA 核心条款摘要

完整条款见 [.github/CLA.md](.github/CLA.md)，核心要点：

- **贡献者声明**：你拥有贡献的版权或有权授权，且不侵犯第三方权利。
- **版权授予**：你授予维护者永久、全球、免费、非独占、不可撤销的版权许可，包括使用、修改、再许可的权利。
- **专利授权**：若贡献涉及你的专利，你授予维护者相应的专利许可。
- **免责声明**：贡献按"现状"提供，不附带任何担保。
- **版权保留**：签署 CLA 不发生版权转让，你保留贡献的全部版权所有权。

### 2.5 CLA 相关问题

如对 CLA 有任何疑问，请联系：

- **邮箱**：security@promiselink.app
- 请勿在公开 Issue 中讨论敏感法律问题，优先使用邮件沟通。

## 3. 贡献流程

### 3.1 Fork & Clone

```bash
# Fork 仓库到你的 GitHub 账户，然后：
git clone https://github.com/<你的用户名>/PromiseLink.git
cd PromiseLink
git remote add upstream https://github.com/lulin70/PromiseLink.git
```

### 3.2 创建分支

```bash
git checkout -b feature/your-feature-name
# 或
git checkout -b fix/issue-123
```

### 3.3 开发环境

```bash
pip install -e ".[dev]"
cp .env.basic.example .env
# 编辑 .env 填入 LLM_API_KEY
```

### 3.4 代码规范

- **Python**: 遵循 ruff 配置（line-length=120）
- **类型**: 遵循 mypy 类型检查
- **测试**: 新功能必须附带测试，不得降低覆盖率
- **文档**: 公共方法必须有 docstring

```bash
# 提交前必须通过
ruff check src/ tests/
python3 -m mypy src/promiselink --ignore-missing-imports
python3 -m pytest tests/ -q
```

### 3.5 提交规范

使用 Conventional Commits 格式：

```
<type>: <description>

type: feat|fix|docs|refactor|test|chore|security
```

示例：
- `feat: 新增日程预定功能`
- `fix: 修复承诺确认状态丢失`
- `docs: 更新安装指南`
- `security: 修复SQL注入风险`

### 3.6 提交 PR

1. Push 到你的 Fork
2. 创建 PR 到 `main` 分支
3. PR 描述需包含：
   - 变更说明
   - 测试方式
   - 是否影响现有功能

## 4. 代码审查标准

PR 需满足以下条件才会被合并：

- [ ] CI 全绿（ruff + mypy + pytest + 前端构建）
- [ ] 测试覆盖率不低于 60%
- [ ] 无新增安全漏洞
- [ ] 无硬编码密钥或内部路径
- [ ] 公共方法有 docstring
- [ ] 未修改 LICENSE 文件
- [ ] 未移除品牌标识
- [ ] CLA 已签署（PR 带 `cla: yes` 标签）

## 5. 报告 Bug

通过 GitHub Issues 报告 Bug，请包含：

- 复现步骤
- 期望行为 vs 实际行为
- 环境信息（Python 版本、操作系统、APP_EDITION）
- 错误日志（脱敏后）

## 6. 安全漏洞报告

**请勿通过公开 Issue 报告安全漏洞。**

发送邮件至：security@promiselink.app

我们会在 48 小时内响应。详细的安全策略与响应承诺见 [SECURITY.md](SECURITY.md)。

## 7. 行为准则

参与本项目即表示你同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 8. 联系方式

- GitHub Issues: 功能建议和 Bug 报告
- Email: security@promiselink.app（安全相关 / CLA 相关）
- 公众号: PromiseLink（产品动态）
