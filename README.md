# BiliDown (B站自动追更下载 + 在线观看系统)

专为 VPS 无头环境设计的 B站视频自动追更、4K下载与 Web 在线流式点播系统。

## ✨ 核心特性

- 🤖 **自动追更**：定时轮询追踪的 UP 主投稿列表，发现新视频自动以 4K 最高画质下载（仅下载追踪时间点之后发布的新视频）。
- 👤 **手动点播**：在 Web 界面输入任意 UP 主 UID，翻页浏览其投稿历史，一键选择下载到 VPS。
- 🎬 **在线流畅观看**：基于 HTML5 `<video>`，支持 HTTP 206 Range 请求拖拽寻道（Seeking）、倍速与全屏播放。
- 🧹 **磁盘自动淘汰**：下载前预估体积，当磁盘空间不足时自动淘汰并清理最旧的已下载视频，保障系统持续运行。
- 🛡️ **高熵路径防御**：全站受 12 位随机高熵路径保护（如 `https://your-domain:8443/{secret_path}/`），未授权或直接扫描一律返回 404 Not Found。
- 🔒 **Cloudflare 15年源证书**：原生支持 HTTPS 直连，完美配合 Cloudflare Full (strict) 代理模式。

---

## 🚀 部署步骤

### 1. 系统要求与环境安装
- **Python** 3.10+
- **FFmpeg**（必须安装，yt-dlp 合并 4K 视频流与音频流所需）

在 Ubuntu / Debian 上安装：
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv ffmpeg
```

### 2. 克隆/配置项目与依赖
```bash
git clone <your-repo> bilidown
cd bilidown

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置 B 站 Cookies (下载 4K 会员必备)
要下载 1080P60、4K 等高码率视频，需要提供大会员账号的 Cookie。
1. 在电脑浏览器登录 B站。
2. 安装扩展插件（如 Chrome 的 **Get cookies.txt LOCALLY**）导出 `bilibili.com` 的 cookies。
3. 保存为 `cookies.txt`，放置在 `bilidown/cookies.txt`。

### 4. 配置 Cloudflare 源服务器证书 (15年)
1. 在 Cloudflare 控制台：选择你的域名 -> **SSL/TLS** -> **源服务器 (Origin Server)**。
2. 点击 **创建证书 (Create Certificate)**，保持默认参数（RSA 2048，有效期 15 年），点击创建。
3. 复制生成的证书内容存为 `certs/origin.pem`。
4. 复制生成的私钥内容存为 `certs/origin-key.pem`。
5. 在 Cloudflare 的 **SSL/TLS 概述** 中，将加密模式设置为 **完整（严格）/ Full (strict)**。
6. 在 DNS 解析中，添加一条 A 记录指向 VPS 公网 IP，并**开启橙色云朵（Proxied）**。

> *注：若暂无域名或证书，系统会自动回退到 HTTP 模式运行。*

### 5. 配置文件说明 (`config.yaml`)
首次运行后，如果 `secret_path` 为空，系统会自动生成一个 12 位的安全随机密钥并写回 `config.yaml`。
```yaml
# === 安全 ===
secret_path: ""     # 首次运行自动生成，如 a7f3e9b2c1d4

# === HTTPS (Cloudflare 源证书) ===
tls_cert: "./certs/origin.pem"
tls_key: "./certs/origin-key.pem"
port: 8443

# === B 站 ===
cookies_file: "./cookies.txt"

# === 下载 ===
download_dir: "./data/videos"
preferred_quality: 2160           # 优先 4K (2160p)，无 4K 则平滑回退
max_concurrent_downloads: 2

# === 轮询 ===
poll_interval_minutes: 5          # 每 5 分钟检查一次新投稿

# === 追踪列表（也可直接在 Web 界面添加）===
tracked_uploaders:
  - mid: 546195
    name: "老番茄"

# === 磁盘管理 ===
disk_reserve_mb: 500              # 始终保留的最小磁盘空间 (MB)
```

### 6. 启动与后台运行 (Systemd 服务)

测试前台启动：
```bash
python3 -m app.main
```
控制台会输出服务监听端口及自动生成的访问密钥。

#### 配置 Systemd 开机自启
创建 `/etc/systemd/system/bilidown.service`：
```ini
[Unit]
Description=BiliDown Video Downloader & Streaming Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/bilidown
ExecStart=/opt/bilidown/venv/bin/python3 -m app.main
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```
启用并启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable bilidown
sudo systemctl start bilidown
sudo systemctl status bilidown
```

---

## 🌐 访问与使用

打开浏览器访问：
```text
https://你的域名:8443/<secret_path>/
```
*(例如：`https://video.yourdomain.com:8443/a7f3e9b2c1d4/`)*

- **视频库**：查看所有已下载视频，点击封面直接在线拖拽播放，支持下载原文件和删除。
- **UP主管理**：输入 UID 即可追踪；系统记录追踪时间点，后续有新投稿即刻自动抓取。
- **浏览视频 (手动下载)**：点击任意 UP 主的“浏览视频”，可以查看历史投稿并手动选择下载到 VPS。
- **系统状态**：实时监控轮询状态、磁盘使用量与下载队列。
