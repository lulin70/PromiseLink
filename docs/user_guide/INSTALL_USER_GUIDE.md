# PromiseLink 基础版安装指南（非技术人员专用）

> **写给谁看**：从未用过命令行的种子用户、一般用户
> **你需要什么**：一台电脑（Mac 或 Windows）、一个许可证密钥（PL-PRO-xxxx-xxxx-xxxx 格式）
> **预计耗时**：15-20 分钟

---

## 这是什么？

PromiseLink 是一款 AI 驱动的个人商务关系管理助手。它会帮你：
- 记录每次与人见面/通话的内容
- 自动提取待办事项、承诺、人脉关系
- 在手机微信小程序里随时查看

**你的数据存在你自己的电脑上，不会上传到云端**（除非你主动使用 AI 分析功能）。

---

## 安装步骤

### 第 1 步：安装 Docker Desktop（5 分钟）

Docker 是一个免费的软件，用来在电脑上运行 PromiseLink。

1. 打开浏览器，访问：https://www.docker.com/products/docker-desktop
2. 点击 **Download for Mac** 或 **Download for Windows**（根据你的电脑系统）
3. 下载完成后，双击安装包，按提示完成安装
4. 安装完成后，**启动 Docker Desktop**（Mac：在"应用程序"里找到 Docker 图标双击；Windows：桌面找到 Docker 图标双击）
5. 等待 Docker 鲸鱼图标出现在菜单栏/任务栏，且显示 **"Docker is running"**

> **如何确认 Docker 已就绪**？
> 打开"终端"（Mac：Command+空格 搜索"终端"；Windows：开始菜单搜索"cmd"），输入：
> ```
> docker info
> ```
> 如果显示一堆信息（而不是报错），说明 Docker 已就绪。

---

### 第 2 步：下载安装脚本（1 分钟）

1. 打开浏览器，访问：https://github.com/lulin70/PromiseLink
2. 找到 `scripts/install_basic.sh` 文件，点击 **Raw** 按钮
3. 右键 → 另存为，保存到桌面，文件名为 `install_basic.sh`

> **不会下载？** 也可以直接在终端运行：
> ```
> curl -o install_basic.sh https://raw.githubusercontent.com/lulin70/PromiseLink/main/scripts/install_basic.sh
> ```

---

### 第 3 步：运行安装脚本（5-10 分钟）

1. 打开"终端"
2. 切换到脚本所在目录（如果保存在桌面）：
   ```
   cd ~/Desktop
   ```
3. 运行安装脚本：
   ```
   bash install_basic.sh
   ```
4. 脚本会依次询问你：
   - **许可证密钥**：输入你收到的 `PL-PRO-xxxx-xxxx-xxxx` 格式密钥
   - **网关地址**：直接按回车使用默认值即可
5. 脚本会自动：
   - 生成配置文件
   - 下载 Docker 镜像（约 200MB，首次需要耐心等待）
   - 启动 PromiseLink 服务
   - 等待健康检查通过

6. 看到下面的提示说明安装成功：
   ```
   ✓ PromiseLink 基础版安装完成！
   ```

> **重要**：脚本会显示你的 **PoC 登录密码**，请记下来！首次登录后可以在设置里修改。

---

### 第 4 步：在电脑上使用（1 分钟）

1. 打开浏览器（Chrome / Safari / Edge 均可）
2. 地址栏输入：`http://localhost:8000`
3. 用刚才记下的 **PoC 登录密码** 登录
4. 进入 PromiseLink 主界面，可以开始：
   - 录入互动记录（会议、通话、见面）
   - 查看待办事项
   - 查看人脉关系
   - 查看承诺追踪

---

### 第 5 步：在手机上使用（3 分钟）

想在手机上也能访问？需要用微信小程序：

1. 在电脑上安装**微信开发者工具**（PC 端工具，不是手机 App）：
   - 下载地址：https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html
2. 打开微信开发者工具，用 AppID `wxa8704555bc066773` 导入 PromiseLink-miniapp 项目
3. 点击工具栏的 **"预览"** 按钮，生成二维码
4. 打开手机微信，**扫一扫** 这个二维码
5. 手机上即可打开 PromiseLink 小程序，访问你电脑上的数据

> **详细的小程序使用说明**：请参阅 [小程序用户指南](../../PromiseLink-miniapp/docs/USER_GUIDE.md)

---

## 常见问题排查

| 问题 | 原因 | 解决方法 |
|------|------|----------|
| 启动报错 "未检测到 Docker" | Docker Desktop 未安装或未运行 | 安装 Docker Desktop 并启动，确认菜单栏有鲸鱼图标 |
| 启动报错 "许可证密钥格式不正确" | 密钥输入错误 | 检查密钥格式应为 `PL-PRO-xxxx-xxxx-xxxx`，联系 support@promiselink.cn 获取 |
| 浏览器打不开 localhost:8000 | 服务未启动成功 | 终端运行 `docker compose ps` 查看状态；运行 `docker compose logs --tail=50` 查看日志 |
| 页面显示 "secret_key must be changed" | 配置文件未正确生成 | 重新运行 `bash install_basic.sh` |
| 小程序无法访问本地数据 | WSS 连接未建立 | 终端运行 `docker compose logs \| grep relay_wss` 查看 WSS 状态 |
| 端口 8000 被占用 | 其他程序占用了该端口 | 编辑 `docker-compose.yml`，把 `8000:8000` 改成 `8001:8000`，然后访问 `localhost:8001` |

---

## 常用命令速查

打开终端，进入安装目录（默认 `~/promiselink`）：

```bash
cd ~/promiselink

# 查看服务状态
docker compose ps

# 查看实时日志
docker compose logs -f

# 停止服务
docker compose down

# 启动服务（停止后重新启动）
docker compose up -d

# 重启服务
docker compose restart
```

---

## 数据备份

你的所有数据存储在：`~/promiselink/data/promiselink.db`

建议每周备份一次：

```bash
cp ~/promiselink/data/promiselink.db ~/promiselink-backup-$(date +%Y%m%d).db
```

---

## 联系支持

- 邮箱：support@promiselink.cn
- 官网：https://promiselink.cn

---

## 下一步

- [小程序用户指南](../../PromiseLink-miniapp/docs/USER_GUIDE.md) — 学习如何在手机上使用
- [隐私政策](../legal/PRIVACY_POLICY.md) — 了解你的数据如何被保护
- [专业版安装指南](../../PromiseLink-Pro/docs/user_guide/PRO_USER_GUIDE.md) — 如需语音、邮件同步等高级功能
