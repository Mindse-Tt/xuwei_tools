---
name: mac-disk-cleaner
description: 安全清理 macOS 磁盘空间(内存/硬盘满了、开机变卡、"磁盘已满"告警时用)。分层处置:先诊断量化 → 只自动删可再生缓存(HuggingFace模型/浏览器/IDE/微信企业微信缓存/brew旧版/node_modules) → 可重下的数据集和安装包确认后删 → 真实数据永不自动删只建议搬移。当用户说"内存炸了/磁盘满了/清理一下/mac变卡/清缓存/腾空间/disk full"时使用。同时能区分"磁盘满(清缓存)"和"内存/swap满(需关App或重启)"两类不同问题。仅适用于 macOS。
---

# mac-disk-cleaner · macOS 磁盘安全清理

把多次真实清理沉淀成一套可复用流程。核心信条:**先量再动 · 只自动删可再生的 · 真实数据永不碰 · 跳过被依赖的缓存**。

## 一键用法
```bash
bash ~/.claude/skills/mac-disk-cleaner/scripts/clean.sh          # 只读诊断(默认)
bash ~/.claude/skills/mac-disk-cleaner/scripts/clean.sh --clean  # 清 Tier1 可再生缓存(零损失)
bash ~/.claude/skills/mac-disk-cleaner/scripts/clean.sh --deep   # 额外清 HuggingFace 模型 + 项目 node_modules/.venv
bash ~/.claude/skills/mac-disk-cleaner/scripts/clean.sh --empty-trash  # 明确清空废纸篓(真实删除)
```

## 第一步永远是分清:磁盘满 还是 内存满?
两者完全不同,别混:
- **磁盘满**(`df` 可用空间少 / "启动磁盘已满"):硬盘塞不下文件 → **本 skill 清缓存有效**。
- **内存/swap 满**(`sysctl vm.swapusage` 显示 swap 用了十几 G、Mac 卡顿转圈):RAM 不够溢出到硬盘 → **清缓存无用**,解法是**关掉占内存的重 App 或重启一次**(重启清空 swap)。

## 分层处置模型(决定"能不能删")
| 层 | 内容 | 处置 |
|---|---|---|
| **0 诊断** | `df -h` 磁盘 + `vm.swapusage` 内存;`du -sh` 排黑洞 | 只读,先量 |
| **1 纯可再生缓存** | `~/Library/Caches/*`、`~/.cache/*`(HuggingFace/codex/puppeteer/uv)、微信·企业微信 App 缓存、`brew cleanup`、`pip/npm/pnpm`、项目 `node_modules`·`.venv`·`__pycache__` | **自动删,零数据损失** |
| **2 可重下 / 安装包** | 挂载的 `.dmg` 镜像(先 `hdiutil detach` 再删源)、公开数据集、下载的 zip、重复副本(`*副本`/`* 2`) | **确认后删** |
| **3 真实数据** | 微信 `msg` 聊天媒体、桌面/文稿、代码项目 | **永不自动删**,只列清单建议搬移动硬盘/网盘 |

## 常见磁盘黑洞速查(去哪找)
- `~/.cache/huggingface` —— ML 模型,常达 10G+(可重下)
- `~/Library/Caches/*` —— 浏览器/IDE(codex/Trae/CodeBuddy)/更新器缓存
- `~/Library/Containers/com.tencent.xinWeChat/.../cache` 与 `.../msg`(msg 是真实聊天媒体,属 Tier3!)
- `~/Library/Containers/com.tencent.WeWorkMac/.../Caches`(cefcache + Videos/Images)
- `~/Library/Containers/com.docker.docker/.../Docker.raw` —— Docker 虚拟盘,常 10G(重置回收)
- `/Volumes/xxx` —— 挂载的安装镜像(装完可 detach + 删源 .dmg)
- 各项目 `node_modules` / `.venv`

## 硬规则(踩坑总结)
1. **删前先看细节**(路径/大小/内容),不信黑盒自动删。
2. **跳过正在被依赖的缓存**:如 `ms-playwright` 的 Chromium 被 Playwright/Firecrawl 依赖,删了会连带坏掉——脚本里用 `SKIP` 变量维护白名单。
3. **删记忆/对话类数据前先备份**(时间戳目录),可一键还原。
4. **系统数据(System Data)真相**:macOS「存储」饼图里的"系统数据"大头,往往就是微信/企业微信/Docker 这些沙盒容器数据,清它们=清系统数据。
5. **TCC 限制**:`~/Library/Containers` 里的东西程序删不动(报 Operation not permitted),只能访达手动拖 或 授予"完全磁盘访问"。
6. **sudo 无法在非交互 shell 输密码**:删 root 文件用 `osascript -e 'do shell script "…" with administrator privileges'`(弹图形授权框)。
7. **缓存必然长回来**,反复满的治本解=搬走 Tier3 真实数据。

## 需要人工/GUI 的收尾(脚本做不了)
- 清空废纸篓才真正释放,但它属于真实删除边界;脚本不会随 `--clean` 自动清,必须用户明确选择 `--empty-trash`。
- Docker 重置、卸载 App、TCC 保护目录、`.dmg` 里的应用安装 —— 走访达/系统设置。

## Agent 执行协议
1. 用户说"内存炸了/磁盘满了/Mac 变卡"时,先运行只读诊断,不要直接清理。
2. 若诊断显示磁盘空间危险,再建议或执行 `--clean`。
3. 若 swap 很高但磁盘空间尚可,明确告诉用户这是内存压力,清缓存不是治本,应关重 App 或重启。
4. Tier2/Tier3 一律先列路径、大小、理由,等用户确认后再删或建议搬移。
5. 废纸篓必须单独确认后才运行 `--empty-trash`。
