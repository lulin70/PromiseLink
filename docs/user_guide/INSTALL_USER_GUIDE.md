# PromiseLink 基础版安装指南（非技术人员专用）

> **写给谁看**：从未用过命令行的目标用户、一般用户
> **你需要什么**：一台电脑（Mac 或 Windows）、一个许可证密钥（PL-PRO-xxxx-xxxx-xxxx 格式）
> **预计耗时**：15 分钟

---

## 这是什么？

PromiseLink 是一款 AI 驱动的个人商务关系管理助手。它会帮你：
- 记录每次与人见面/通话的内容
- 自动提取待办事项、承诺、人脉关系
- 在手机微信小程序里随时查看

**你的数据存在你自己的电脑上，不会上传到云端**（除非你主动使用 AI 分析功能）。

---

## 安装步骤

### 第 1 步：下载安装包（2 分钟）

1. 打开浏览器，访问：https://www.promiselink.cn/download.html
2. 根据你的电脑系统下载对应的安装包：

   | 系统 | 下载文件 |
   |------|---------|
   | macOS（Apple Silicon / Intel） | `PromiseLink-<版本号>-mac.dmg` |
   | Windows 10/11 64 位 | `PromiseLink-<版本号>-windows.exe` |

> 安装包已内置 Python 运行时和全部依赖，**不需要安装 Python、Node.js，也不需要安装 Docker**。

---

### 第 2 步：安装并启动（2 分钟）

**macOS**：
1. 双击下载好的 `.dmg` 文件
2. 在弹出的窗口中，把 PromiseLink 图标拖到「应用程序」文件夹
3. 打开「应用程序」，双击 PromiseLink 启动

**Windows**：
1. 双击下载好的 `.exe` 文件
2. 按安装向导的提示点击「下一步」直到完成
3. 在开始菜单中找到 PromiseLink，双击启动

启动后本地服务会自动运行，**浏览器会自动打开** http://localhost:8000 ，能看到 PromiseLink 页面即表示启动成功。

> 若浏览器没有自动打开，请手动打开浏览器（Chrome / Safari / Edge 均可），在地址栏输入 `http://localhost:8000`。

---

### 第 3 步：登录电脑端（1 分钟）

在浏览器页面使用本地管理员密码登录。默认密码为 `promiselink2026`（管理员可能会为你改成其他密码）。

进入 PromiseLink 主界面后，可以开始：
- 录入互动记录（会议、通话、见面）
- 查看待办事项
- 查看人脉关系
- 查看承诺追踪

---

### 第 4 步：在手机上使用（3 分钟）

想在手机上也能访问？需要用微信小程序：

- **小程序正式发布后**：打开手机微信，在搜索框输入"PromiseLink"，点击搜索结果中的小程序即可使用
- **发布前内测阶段**：请联系 support@promiselink.cn 获取内测二维码，用微信扫一扫打开

**把手机和电脑配对**：

1. 在电脑端浏览器打开配对页面：http://localhost:8000/pair
2. 页面会显示一个二维码
3. 用手机微信扫一扫扫描该二维码
4. 电脑端提示"激活成功"后，即可用手机访问电脑上的数据

> **前提**：你的电脑必须保持开机且 PromiseLink 正在运行（第 2 步启动的程序）。手机小程序通过云端网关中继访问你电脑上的数据，关闭电脑则手机无法访问。
>
> 配对成功后，许可证会写入你电脑上的配置文件，**重启电脑后无需重新配对**。

> **详细的小程序使用说明**：请参阅 [小程序用户指南](https://promiselink.cn/docs/miniapp-user-guide)

---

## 常见问题排查

| 问题 | 原因 | 解决方法 |
|------|------|----------|
| 浏览器打不开 localhost:8000 | 程序未启动成功 | 确认菜单栏 / 任务栏有 PromiseLink 图标；退出后重新双击启动 |
| 页面提示需要登录但不知道密码 | 未拿到本地登录密码 | 默认密码为 `promiselink2026`；如管理员已修改，请联系 support@promiselink.cn |
| 小程序提示"本地基础版未连接" | 电脑关机、程序未运行或未完成配对 | 确认电脑开机 + PromiseLink 运行中；重新打开 http://localhost:8000/pair 扫码配对 |
| 想修改登录密码 | 需要修改本地配置 | 编辑配置文件后重启程序（见下方「配置文件位置」） |
| 端口 8000 被占用 | 其他程序占用了该端口 | 关闭占用 8000 端口的程序后重启 PromiseLink |

---

## 数据与配置文件位置

| 内容 | 位置 |
|------|------|
| 业务数据（SQLite 数据库） | `~/.promiselink/data/promiselink.db` |
| 本机配置（许可证 / LLM Key / 登录密码） | `~/.promiselink/.env` |

> Windows 用户：`~` 即 `%USERPROFILE%`（例如 `C:\Users\你的用户名`）。

---

## 数据备份

建议每周备份一次。**先退出 PromiseLink**（避免写入冲突），然后复制数据库文件：

```bash
# macOS / Linux
cp ~/.promiselink/data/promiselink.db ~/promiselink-backup-$(date +%Y%m%d).db
```

```powershell
# Windows PowerShell
Copy-Item "$env:USERPROFILE\.promiselink\data\promiselink.db" "$env:USERPROFILE\promiselink-backup-$(Get-Date -Format yyyyMMdd).db"
```

> **恢复方法**：先退出 PromiseLink，再用备份文件覆盖上面的数据库文件，最后重新启动 PromiseLink。

---

## 联系支持

- 邮箱：support@promiselink.cn
- 官网：https://promiselink.cn

---

## 下一步

- [小程序用户指南](../../PromiseLink-miniapp/docs/USER_GUIDE.md) — 学习如何在手机上使用
- [隐私政策](../legal/PRIVACY_POLICY.md) — 了解你的数据如何被保护
- [专业版安装指南](../../PromiseLink-Pro/docs/user_guide/PRO_USER_GUIDE.md) — 如需语音、邮件同步等高级功能