#!/bin/bash
# 构建 .app 外壳。必须有这一层，程序才有独立的 TCC 身份，
# macOS 才会弹「系统音频录制」授权框。命令行直接跑 python 是拿不到的。
set -e
cd "$(dirname "$0")"
APP="微信实时字幕.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>微信实时字幕</string>
  <key>CFBundleDisplayName</key><string>微信实时字幕</string>
  <key>CFBundleIdentifier</key><string>local.xuwei.wechatlivecaption</string>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>2.0</string>
  <key>CFBundleVersion</key><string>2</string>
  <key>LSMinimumSystemVersion</key><string>14.4</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAudioCaptureUsageDescription</key>
  <string>需要捕获微信的音频输出，用于在本机生成实时字幕。音频不会被保存或上传。</string>
  <key>NSMicrophoneUsageDescription</key>
  <string>需要访问麦克风，用于识别你自己说的话。音频不会被保存或上传。</string>
</dict>
PLIST
echo "</plist>" >> "$APP/Contents/Info.plist"

cat > "$APP/Contents/MacOS/launch" <<'LAUNCH'
#!/bin/bash
BUNDLE="$(cd "$(dirname "$0")/../.." && pwd)"
PROJ="$(dirname "$BUNDLE")"
cd "$PROJ" || exit 1
exec ./.venv/bin/python app_mac.py "$@" > "$PROJ/last_run.log" 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/launch"

codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true
echo "已生成 $APP"
