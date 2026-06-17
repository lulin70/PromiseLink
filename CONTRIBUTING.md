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

## 2. 贡献流程

### 2.1 Fork & Clone

```bash
# Fork 仓库到你的 GitHub 账户，然后：
git clone https://github.com/<你的用户名>/PromiseLink.git
cd PromiseLink
git remote add upstream https://github.com/lulin70/PromiseLink.git
```

### 2.2 创建分支

```bash
git checkout -b feature/your-feature-name
# 或
git checkout -b fix/issue-123
```

### 2.3 开发环境

```bash
pip install -e ".[dev]"
cp .env.basic.example .env
# 编辑 .env 填入 LLM_API_KEY
```

### 2.4 代码规范

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

### 2.5 提交规范

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

### 2.6 提交 PR

1. Push 到你的 Fork
2. 创建 PR 到 `main` 分支
3. PR 描述需包含：
   - 变更说明
   - 测试方式
   - 是否影响现有功能

## 3. 代码审查标准

PR 需满足以下条件才会被合并：

- [ ] CI 全绿（ruff + mypy + pytest + 前端构建）
- [ ] 测试覆盖率不低于 60%
- [ ] 无新增安全漏洞
- [ ] 无硬编码密钥或内部路径
- [ ] 公共方法有 docstring
- [ ] 未修改 LICENSE 文件
- [ ] 未移除品牌标识

## 4. 报告 Bug

通过 GitHub Issues 报告 Bug，请包含：

- 复现步骤
- 期望行为 vs 实际行为
- 环境信息（Python 版本、操作系统、APP_EDITION）
- 错误日志（脱敏后）

## 5. 安全漏洞报告

**请勿通过公开 Issue 报告安全漏洞。**

发送邮件至：security@promiselink.app

我们会在 48 小时内响应。

## 6. 行为准则

参与本项目即表示你同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 7. 联系方式

- GitHub Issues: 功能建议和 Bug 报告
- Email: security@promiselink.app（安全相关）
- 公众号: PromiseLink（产品动态）
