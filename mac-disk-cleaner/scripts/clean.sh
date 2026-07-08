#!/usr/bin/env bash
# mac-disk-cleaner —— 分层安全清理 macOS 磁盘
# 用法:
#   bash clean.sh                只读诊断(默认,不删任何东西)
#   bash clean.sh --clean        清 Tier1(纯可再生缓存,零数据损失)
#   bash clean.sh --deep         在 --clean 基础上,额外清 HuggingFace 模型 + 项目 node_modules/.venv
#   bash clean.sh --empty-trash  额外清空废纸篓(真实删除,需用户明确选择)
#
# 设计原则:先量再动 | 只自动删可再生的 | 真实数据永不碰 | 跳过被依赖的缓存
set -uo pipefail

usage() {
  cat <<'EOF'
mac-disk-cleaner

Usage:
  bash clean.sh                Diagnose only. No files are deleted.
  bash clean.sh --clean        Delete Tier1 regenerable caches.
  bash clean.sh --deep         Delete Tier1 + heavy rebuildable caches/deps.
  bash clean.sh --empty-trash  Empty ~/.Trash explicitly.
  bash clean.sh --help         Show this help.

Safety model:
  - Diagnose first.
  - --clean only targets regenerable caches.
  - Trash and real user data are never deleted unless explicitly requested.
EOF
}

case "$(uname -s)" in
  Darwin) ;;
  *) echo "mac-disk-cleaner only supports macOS." >&2; exit 2 ;;
esac

MODE="${1:-diagnose}"
case "$MODE" in
  diagnose|--clean|--deep|--empty-trash) ;;
  -h|--help) usage; exit 0 ;;
  *) echo "未知参数: $MODE" >&2; usage >&2; exit 2 ;;
esac

DATA=/System/Volumes/Data
avail(){ df -h "$DATA" | tail -1 | awk '{print $4}'; }
used(){ df -h "$DATA" | tail -1 | awk '{print $5}'; }

# 被活跃工具依赖、默认不删的缓存(按需增减)
SKIP="ms-playwright ms-playwright-mcp"   # 例:Firecrawl / Playwright 依赖其中的 Chromium

echo "════════ mac-disk-cleaner ════════"
echo "【0 诊断】"
echo "  磁盘可用: $(avail)   已用: $(used)"
sw=$(sysctl -n vm.swapusage 2>/dev/null | sed 's/.*used = //; s/ free.*//')
echo "  swap 已用: ${sw:-未知}  (swap 高=内存不够,清缓存无用,需关App/重启)"
echo "  —— 缓存黑洞 top ——"
du -sh ~/.cache ~/Library/Caches 2>/dev/null | sort -rh
du -sh ~/Library/Caches/* 2>/dev/null | sort -rh | head -8 | sed 's/^/    /'
echo "  —— 微信/企业微信 App 缓存 ——"
du -sh ~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/*/cache 2>/dev/null | sort -rh | head -2 | sed 's/^/    /'
trash_size=$(du -sh ~/.Trash 2>/dev/null | awk '{print $1}')
echo "  废纸篓: ${trash_size:-未知}  (不会随 --clean 自动清空; 用 --empty-trash 显式清)"

if [ "$MODE" = "diagnose" ]; then
  echo
  echo "只读模式。加 --clean 清 Tier1(可再生缓存),--deep 连模型/依赖一起清。"
  exit 0
fi

if [ "$MODE" = "--empty-trash" ]; then
  echo
  echo "【清空废纸篓】清理前 $(avail)"
  rm -rf ~/.Trash/* 2>/dev/null && echo "  ✓ 废纸篓"
  echo "【完成】清理后 $(avail)"
  exit 0
fi

echo
echo "【1 清理 Tier1:纯可再生缓存(零数据损失)】清理前 $(avail)"
# 1a. ~/Library/Caches 下的可再生项(跳过 SKIP)
for d in ~/Library/Caches/*; do
  [ -e "$d" ] || continue
  b=$(basename "$d")
  case " $SKIP " in *" $b "*) echo "  ⊘ 跳过(被依赖): $b"; continue;; esac
  rm -rf "$d" 2>/dev/null
done
echo "  ✓ ~/Library/Caches/*(除 $SKIP)"
# 1b. ~/.cache 开发/AI 工具缓存
rm -rf ~/.cache/puppeteer ~/.cache/uv ~/.cache/rod ~/.cache/clang ~/.cache/chrome-devtools-mcp 2>/dev/null
echo "  ✓ ~/.cache 工具缓存"
# 1c. 微信 / 企业微信 App 缓存(非聊天记录)
rm -rf ~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/*/cache/* 2>/dev/null
rm -rf ~/Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/*/Caches/* 2>/dev/null
rm -rf ~/Library/Containers/com.tencent.WeWorkMac/Data/Documents/cefcache/* 2>/dev/null
echo "  ✓ 微信/企业微信 缓存(聊天记录保留)"
# 1d. Homebrew 旧版本 + 下载缓存
if command -v brew >/dev/null 2>&1; then brew cleanup -q 2>/dev/null && echo "  ✓ brew cleanup"; fi
echo "  ⊘ 废纸篓未清空(真实删除需显式运行 --empty-trash)"

if [ "$MODE" = "--deep" ]; then
  echo
  echo "【1-deep 额外清理:模型 + 项目依赖(可重建,但要重下/重装)】"
  du -sh ~/.cache/huggingface 2>/dev/null | sed 's/^/    HF模型: /'
  rm -rf ~/.cache/huggingface 2>/dev/null && echo "  ✓ HuggingFace 模型缓存(用时自动重下)"
  echo "  扫描项目 node_modules/.venv ..."
  find ~/Desktop ~/Downloads ~/Documents -type d \( -name node_modules -o -name .venv -o -name venv -o -name __pycache__ -o -name .pytest_cache \) -prune 2>/dev/null -exec rm -rf {} + 2>/dev/null
  echo "  ✓ 项目 node_modules/.venv/__pycache__(pip/npm install 可重建)"
fi

echo
echo "【完成】清理后 $(avail)  (清理前见上)"
echo "提示:缓存会长回来。若反复满,治本=把真实数据(聊天媒体/数据集/旧项目)搬去移动硬盘/网盘。"
