# 🧹 mac-disk-cleaner · macOS 磁盘安全清理

> 内存/硬盘满了、开机变卡、"磁盘已满"告警时,一套**先量再动、只删可再生、真实数据永不碰**的分层清理流程。
>
> A layered, safe macOS disk cleaner: diagnose first, auto-delete only regenerable caches, never touch real data.

## 它解决什么 · Why

Mac 用久了反复"磁盘满",手动找又慢又怕误删。这个工具把多次真实清理沉淀成**可复用的分层流程 + 一键脚本**:该自动删的自动删(缓存零损失),该确认的确认,真实数据只建议搬走绝不乱删。还能帮你**分清"磁盘满"和"内存满"**——两者解法完全不同。

## 快速用 · Quick start

```bash
# 只读诊断(默认,不删任何东西)——先看清现状
bash scripts/clean.sh

# 清 Tier1:纯可再生缓存(HuggingFace模型/浏览器/IDE/微信企业微信缓存/brew旧版…)零数据损失
bash scripts/clean.sh --clean

# 更狠:额外清 HuggingFace 模型 + 项目 node_modules/.venv(可重建,但要重下/重装)
bash scripts/clean.sh --deep
```

## 核心方法 · The method

**第一步永远先分清:磁盘满 还是 内存满?**
- **磁盘满**(`df` 可用少)→ 清缓存有效,用本工具。
- **内存/swap 满**(`sysctl vm.swapusage` 显示 swap 十几 G、卡顿)→ 清缓存**没用**,得关重 App 或**重启**。

**分层处置(决定能不能删):**

| 层 | 内容 | 处置 |
|---|---|---|
| 0 诊断 | `df` 磁盘 + swap 内存 + `du` 排黑洞 | 只读,先量 |
| 1 纯可再生缓存 | `~/Library/Caches`、`~/.cache`、微信/企业微信缓存、`brew cleanup`、`node_modules`/`.venv` | 自动删,零损失 |
| 2 可重下/安装包 | `.dmg` 镜像、公开数据集、下载的 zip、重复副本 | 确认后删 |
| 3 真实数据 | 聊天媒体、桌面文件、代码项目 | 永不自动删,只建议搬移 |

## 硬规则(踩坑总结) · Hard rules
1. 删前**先看细节**(路径/大小),不信黑盒。
2. **跳过被依赖的缓存**(如 `ms-playwright` 被 Playwright/Firecrawl 依赖)——脚本用 `SKIP` 变量维护白名单。
3. 删记忆/对话类数据前**先备份**。
4. `~/Library/Containers` 受 TCC 保护,程序删不动 → 访达手动拖 或 给"完全磁盘访问"。
5. 删 root 文件用 `osascript -e 'do shell script "…" with administrator privileges'`(弹图形授权,免 sudo 无 TTY 问题)。
6. **缓存必然长回来**,反复满的治本解 = 搬走真实数据。

## 怎么挂到 AI 里 · Use with AI
把 `SKILL.md` 放进 `~/.claude/skills/mac-disk-cleaner/`(Claude Code),或直接把内容贴给任意 AI 当系统提示。之后说一句"磁盘满了帮我清"即可触发。

## ⚠️ 仅适用于 macOS。脚本默认只读,`--clean`/`--deep` 才会删。
