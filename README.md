# 拾图

个人 Android 图片收藏工具。QQ 接入、下载及清理独立运行在服务器，App 负责浏览和整理。普通图片默认保留 120 小时，收藏长期保留。B 站属于后续阶段。

## 本地开发

需要 Python 3.13、Node.js 22 或更新版本、JDK 21、Android SDK 36。Python 环境安装 `backend/requirements.lock`，前端在 `app` 执行 `npm ci`。

```powershell
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.lock
.venv/Scripts/python -m collector.cli init
.venv/Scripts/python -m uvicorn collector.api:app --host 127.0.0.1 --port 8000
```

`init` 创建数据库并交互设置管理员密码（至少 12 位）。另开终端在 backend 目录设置 DATA_DIR（与 API 相同）和 INGEST_TOKEN（至少 32 位随机字符串），运行 `python -m uvicorn collector.worker:app --host 127.0.0.1 --port 8001`。仅启动 API 不会采集图片。

前端：在 app 执行 `npm run dev`。浏览器开发仅允许 localhost 的 HTTP 地址；Android 正式连接要求 HTTPS。登录会话保存在内存，重启 App 后需要重新登录。

## 云服务器部署

1. 安装 Docker Engine 和 Compose，准备解析到服务器的域名，开放 80/443。数据库和媒体保存在同机 Docker 卷，不使用网络共享盘。
2. 将 deploy/.env.example 复制为 deploy/.env，填 DOMAIN、随机 INGEST_TOKEN。不要提交实际文件。
3. 在 deploy 运行 `docker compose up -d --build`。API 自动迁移并清理，worker 等待 API 健康后启动，Caddy 自动申请证书。
4. 运行 `docker compose exec api python -m collector.cli password`，交互设置管理员密码。
5. App 填写 `https://你的域名` 后登录，添加目标群号。

`DATA_DIR` 默认 /data。Compose 中只有 HTTPS 入口对公网开放；OneBot 事件入口仅绑定服务器 127.0.0.1:8001。不要公开该端口或 QQ 管理面板。

## QQ 接入

当前适配 OneBot v11 HTTP POST 群消息数组。已有 NapCat 等接入程序需配置：

- 上报 URL 使用本机 worker 端口。systemd 部署填 `http://127.0.0.1:18001/events/onebot`，默认 Docker Compose 部署使用端口 `8001`。
- NapCat 使用「HTTP 客户端」，Token 填 `INGEST_TOKEN` 的值。拾图校验 NapCat 发送的 `X-Signature`（对原始请求体计算 HMAC-SHA1）。其他接入程序也可以使用 `Authorization: Bearer <INGEST_TOKEN>`。
- 消息格式选择 array；图片段必须提供可下载的公网 HTTPS `data.url`。本地文件路径和内网下载地址被拒绝。
- 启用心跳，建议间隔 30 秒；`status.online` 决定来源页的连接提示，120 秒无心跳显示异常。
- 接入程序若在容器中，localhost 指向自身，应通过私有容器网络访问 worker:8001；不要为方便配置而公开入口。

事件必须有 self_id、group_id、message_id、time、user_id、message 数组。仅接收 App 中启用的群。重复事件不会重复保存或延长有效期。群名使用用户设置的名称，来源记录不承诺跳转 QQ 原消息。真实账号是否能接收到普通群图片仍需现场验证。

## 定时图片识别

在拾图「设置」填写每日识别时间（北京时间）和中文保留规则，可先用「试跑规则」检查最近最多六张图片。试跑只展示判断和理由。开启定时识别后，首次运行处理图库中符合该批截止时间的图片，以后处理新图片及上次因故失败的图片。修改保留规则后，下批重新按新规则判定。

识别使用 DeepSeek 的 `deepseek-flash`，只发送缩略图和保留规则。明确不符合规则且未收藏的图会从图库删除，文件由定时清理回收。已收藏、待确认、接口失败的图片不参与自动删除。可选让符合规则的图片自动收藏，否则仍按普通图片的期限保留。

systemd 部署在仅管理员可读的 `/etc/shitu.env` 中设置 `DEEPSEEK_API_KEY`，完成数据库迁移后重启 `shitu-api` 和 `shitu-worker`。Compose 部署通过 `.env` 提供相同变量。API 和 worker 都应读取该配置，网页不会读取密钥。此功能默认关闭。

## APK 构建和安装

在 app 执行 `npm run android`，再进入 app/android 执行 `gradlew.bat assembleDebug`（Linux 用 ./gradlew）。JAVA_HOME 指向 JDK 21；local.properties 的 sdk.dir 指向本机 Android SDK。

测试包输出在 app/android/app/build/outputs/apk/debug/app-debug.apk。支持 Android 10 及更新版本。测试包使用开发签名，正式长期使用应在 Android Studio 的 Generate Signed Bundle / APK 中选择 APK，创建存放在仓库外的专用签名密钥并离机备份。后续升级保持应用 ID 和密钥不变，递增 versionCode。

相册通过 MediaStore 保存至 Pictures/Shitu，不申请全文件权限。分享通过受限 FileProvider 临时授权。安装后必须实测大图、空间不足、系统分享和覆盖升级，编译成功不能替代真机验收。

## 运维和恢复

- 来源页查看 QQ 心跳、worker 心跳、失败下载；失败任务可以手动重试，但不会延长有效期。
- 定时清理每 15 分钟执行，API 实时过滤到期图片。收藏和未过期内容不会因容量不足自动删除。
- 容量预算需要为一张最大图片预留 25 MiB；实际磁盘额外保留 100 MiB。磁盘或预算不足时暂停该任务，调整后手动重试。
- 修改保留天数按原接收时间重新计算，已经物理删除的内容无法恢复。
- `docker compose exec api python -m collector.cli backup --output /data/backup-日期` 创建一致性数据库快照和收藏原图/缩略图。必须将结果复制到服务器外并按日期轮换，完成后移除服务器上的备份副本；本项目不自动选择远程备份服务。
- 恢复前停止 api 和 worker，将备份的 collector.db 和 media 目录放回数据卷（属主 UID 10001）。运行迁移和 cleanup，再启动服务。备份仅包含收藏媒体；会话已撤销，需重新登录。保留去重凭据，旧事件不会复活已清理内容。
- 密码重置使用 `python -m collector.cli password`，会同时撤销全部会话。

## 测试与验收

```text
# backend 目录，确保 collector 在 Python 导入路径
python -m pytest tests/test_system.py -q
# app 目录
npm test
npm run build
npm run test:e2e
# 仓库根目录
python -B -m unittest discover -s tests -v
```

Playwright 使用 Windows Edge，并启动隔离的临时数据库及测试图片服务。项目本机配置使用根目录 .python/python.exe；其他环境请调整 playwright.config.ts 的 Python 可执行路径。截图保存在 tests/screenshots。

详细范围见 [产品设计](PRODUCT.md)、[技术方案](TECHNICAL_PLAN.md)和[验收清单](tests/ACCEPTANCE.md)。当前结果及未验证事项见[进度记录](docs/PROGRESS.md)。

## 无域名的私有部署

在 deploy 设置 .env 中的 INGEST_TOKEN，执行 `docker compose -f compose.private.yaml up -d --build`。API 仅监听服务器 127.0.0.1:18000，事件入口仅监听 127.0.0.1:18001，不启动 Caddy，不占用已有网站端口。

通过 SSH 隧道进行本机验证：`ssh -L 18000:127.0.0.1:18000 root@服务器IP`。浏览器开发界面可使用 http://127.0.0.1:18000。Android 仍需要可信 HTTPS 地址；私有部署并不等于手机已可公网访问。

## systemd 部署（镜像仓库不可达时）

将 backend 上传至 /opt/shitu/backend，用 Python 3.12 或 3.13 创建 /opt/shitu/venv 并安装 requirements.lock，随后以 root 执行 deploy/install-systemd.sh。脚本创建专用 shitu 用户、/var/lib/shitu 数据目录、/etc/shitu.env 接入令牌和两个开机自启服务。API/worker 分别仅监听 127.0.0.1:18000/18001。

首次生成的 App 管理员密码在服务器 /opt/shitu/admin-password.txt（仅 root 可读），不是 SSH 密码。通过 SSH 安全读取后妥善保存；不要发到聊天或提交仓库。日志使用 `journalctl -u shitu-api -u shitu-worker`，重启使用 `systemctl restart shitu-api shitu-worker`。这条路径使用 systemd 而不是 Docker，二者不要同时连接同一数据库运行 worker。
