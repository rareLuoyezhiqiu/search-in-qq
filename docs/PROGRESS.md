# 开发进度与接续记录

更新时间：2026-11-18（北京时间）。用户要求关机暂停，明天继续。

## 用户要求与范围

- 根据 PRODUCT.md 和 TECHNICAL_PLAN.md 实现 Android App + 云端 QQ 图片采集产品。
- 用户已说明有云服务器、HTTPS 域名及 QQ 接入环境，连接信息稍后提供；尚未收到具体信息。
- 遵循 AGENTS.md：每次改动更新测试并创建 git commit。
- 当前提交是暂停时的工作进度快照，不是验收完成的发布版本。

## 已写入的实现

- backend/collector：FastAPI API、SQLAlchemy/SQLite 持久存储、独立 OneBot v11 HTTP 事件入口与 worker。
- 消息去重凭据、图片 SHA-256 去重、原图及缩略图、下载租约与重试、容量检查、过期清理、收藏、标签备注和中文搜索。
- 单账号 Argon2 密码哈希、可撤销的会话、鉴权图片接口、登录尝试限制、HTTPS 下载和公网 IP 校验。
- Alembic 初始迁移、初始化/密码重置/清理/收藏备份 CLI。
- app：Vue 3 + TypeScript + Capacitor 8，登录、图库、详情、收藏编辑、来源管理、失败重试、存储设置，内存图片缓存。
- Android 工程及自定义 MediaStore 相册保存/系统分享插件；最低 Android 10，避免请求全文件访问权限。尚未生成 APK 和原生验收。
- deploy：Dockerfile、Compose、Caddy 配置示例。尚未部署验证。
- backend/tests/test_system.py：16 项集成用例（含参数化），使用真实 SQLite 和图片文件。
- app/src/api.test.ts：3 项前端测试；app/e2e/flows.spec.ts：真实 API + Chrome 的界面流程测试及截图脚本。

## 已执行的验证

- npm run build（app）：通过，TypeScript 检查和 Vite 生产构建成功。
- npm test（app）：3 项通过，0 失败。
- npm 依赖审计：将 Vitest 升级到 5.1.0 后安装输出为 0 vulnerabilities。
- 后台首轮：15 通过、1 失败。失败原因是测试推进清理时间后会话被正确删除；已修改用例重新登录，等待最终复跑结果。
- Android 首次构建失败：现有 Android Studio JDK 25 与 Gradle 8.14.3 不兼容（class file version 69）。需要 JDK 21。
- 已启动下载微软 JDK 21 到项目本地 jdk21.zip/.jdk21（已忽略），关机时可能未完成。
- 已启动后台复跑及 Playwright 验证，最终结果以会话日志和下次复跑为准，不能当作已通过。

## 明天建议顺序

1. git status 和本文件确认进度。运行后台全部测试，修复失败；不得把当前快照当成验收通过。
2. 完成 JDK 21 下载/解压，设置 JAVA_HOME 为该 JDK；Android SDK 在 D:/AndroidDev/Sdk。执行 app/android/gradlew.bat assembleDebug。
3. 跑 npm run test:e2e，检查 tests/screenshots 的手机及宽屏截图；修复界面问题后重新截图。
4. 补足部署说明 README、真实 QQ 接入验证清单、APK 安装及签名更新步骤、备份恢复步骤。
5. 进一步审查并补测：下载中到期、孤立文件巡检、真实网络下载重定向/DNS 安全、收藏与清理并发、备份恢复、Android 相册/分享与缓存限制。
6. 来源状态和 API 返回值、分页排序与性能、错误输入校验、前端缓存过期刷新仍需系统审查。
7. 按 de-slop 技能检查界面：去掉与中文标题重复的英文眉标、过小字号和纯装饰符号；当前未完成视觉验收。
8. 最终跑所有测试、git diff --check，更新测试记录并提交。
9. 收到用户云环境信息后接入真实 QQ 群，完成真机及持续一周试用；B 站接入按文档列为第二阶段。

## 本机环境与命令

- 默认 python 是 MSYS Python，没有原生 Windows 依赖环境；py 启动器未发现已安装 Python。
- 项目本地 .python/python.exe 是下载的 CPython 3.13.9，已安装 backend/requirements.lock 中依赖。
- .python/python313._pth 已增加 ../backend，便于导入 collector；此本地运行时不进 Git。
- 后台：根目录 ./.python/python.exe -m pytest backend/tests -q。
- 文档：python -B -m unittest discover -s tests -v。
- 前端：cd app；npm ci；npm test；npm run build；npm run test:e2e。
- Playwright 配置会启动本地 Vite 5173 和测试 API 8765；测试专用临时数据，不是真实采集数据。
- 沙箱阻止本机套接字：FastAPI TestClient 在沙箱内挂起，需允许执行本机测试；浏览器测试也需允许本机进程与回环网络。
- app/android/local.properties 指向本机 SDK，已被忽略，不提交机器特定路径。
- 未创建部署账户、未连接真实 QQ、未写入真实凭据；所有本地测试密码仅用于测试。

## 需要注意的实现差异

- 为防 DNS rebinding，生产图片下载使用标准库 HTTPSConnection，将已校验公网 IP 固定到连接并保留 TLS 主机名验证；HTTPX 用于测试客户端。
- 当前会话仅存内存，重启 App 需重新登录；没有把凭据写入 localStorage。
- 当前前端可通过 Vite 在浏览器中开发验证，最终交付目标仍为 APK，不是独立电脑网页产品。

### 暂停收尾补充

- 文档检查实际执行结果：4 项通过；git diff --check 通过。
- 用户暂停后，自动审批拒绝了之前排队的浏览器端到端测试，因此该测试未执行；后续后台复跑也未启动。
- 已停止遗留的沙箱挂起测试和 JDK 下载任务；JDK 压缩包可能不完整，继续前需重新下载核验。
- 暂存后的完整差异检查发现 5 处空白格式问题（AndroidManifest.xml、android/build.gradle、App.vue、service.py、test_system.py）；暂停时保留原样，明天修复后重新检查。此前 unstaged diff 检查没有覆盖未跟踪的新文件，不能作为完整检查通过的依据。
- 工作快照提交：f862f48。此次保存只保证源文件和接续信息持久化，不表示全部功能测试通过。
