# WeChatLiveCaption for macOS

> 独立仓库（含 issue / release）：https://github.com/Mindse-Tt/wechat-live-caption-mac

给 macOS 微信语音/视频通话加**实时中文字幕**，并且**只抓微信一个 App 的声音**。

不用装虚拟声卡，不用付费工具，全程本地推理，音频不上传。

---

## TL;DR

原项目是 Windows 版，靠 VB-CABLE 虚拟声卡 + 音量混合器按应用选输出设备实现"只抓微信"。
macOS 没有按 App 选输出设备的功能，所以这条路在 Mac 上走不通。

这个版本换了条路：用 macOS 14.4 新增的 **Core Audio Process Tap** 直接对微信进程的音频输出打点。
能力等价，而且不需要任何驱动。

顺手做了三件原版没有的事：

- **说话人区分**：对方走 tap，自己走麦克风，两路物理隔离，100% 准确，不靠声纹模型猜
- **通话自动检测**：微信一进通话就自动开字幕，挂断自动停
- **瘦身**：FunASR + PyTorch + PySide6 约 3GB → sherpa-onnx + tkinter **约 400MB**

---

## 特性

| | |
|---|---|
| 只抓微信 | Core Audio Process Tap，不混进音乐和系统音 |
| 说话人区分 | 「对方」「我」两行分开显示 |
| 标点断句 | x-asr 流式模型自带标点，支持中英混说 |
| 自动开关 | 检测微信是否占用麦克风来判断通话 |
| 四种摆位 | 贴着微信窗口自动跟随 / 屏幕左右 / 底部横条 |
| 纯本地 | 装完即可断网使用 |

实测 Apple Silicon 上实时率 **0.02x**（7.3 秒音频算 0.1 秒）。

---

## 快速开始

```bash
git clone <this-repo>
cd WeChatLiveCaption-mac
./install.sh
```

然后**双击 `微信实时字幕.app`**，点「开始」。

> ⚠️ 必须走 `.app`，不能用 `./start.sh`。
> 命令行里的 python 没有独立的 TCC 身份，拿不到「系统音频录制」授权，
> 而 macOS 对未授权的 tap 是**静默返回全零**——不报错，就是没字幕。
> 这个坑我踩了两小时，特此标注。

首次运行会弹授权框，点允许。没弹的话手动开：
`系统设置 → 隐私与安全性 → 屏幕与系统音频录制`，开完要完全退出程序再重开。

---

## 工作原理

```
微信通话
   │
   ├─ 对方的声音 ──→ 微信音频输出
   │                      │
   │              AudioHardwareCreateProcessTap
   │                      │
   │              私有聚合设备（master 指向真实输出设备提供时钟）
   │                      │
   │              PortAudio 当普通输入设备读
   │                      │
   └─ 我的声音 ──→ 麦克风 ─┤
                          │
                   16kHz 单声道 / RMS 静音门限
                          │
                sherpa-onnx 流式 zipformer（一个模型，两个 stream）
                          │
                   tkinter 无边框置顶悬浮窗
```

关键点：

1. **进程定位**：`kAudioHardwarePropertyProcessObjectList` 枚举所有有音频的进程，
   按 bundle id `com.tencent.xinWeChat` 过滤。
2. **聚合设备必须有时钟**：只挂 tap、`subdevices` 为空时，聚合设备没有时钟源，
   读出来全是静音。必须把 `master` 设成真实输出设备的 UID。这一步官方文档没讲清楚。
3. **不静音**：`CATapDescription.muteBehavior = 0`，通话声音照常从耳机出，不打断你听。
4. **通话检测**：查微信进程的 `kAudioProcessPropertyIsRunningInput`。
   放语音消息只占扬声器，只有真通话才占麦克风，这个信号很干净。

---

## 已知限制

- **群语音分不出人**：3 人以上时"对方"那一路是混音。要分需要声纹聚类模型。
- **中途换耳机要重启**：聚合设备的时钟设备在启动时锁定。
- **必须先让微信出过声**：没进过音频进程列表就找不到它。

---

## 致谢

移植自 [cengyingte-stack](https://github.com/cengyingte-stack) 的 Windows 版本，
识别链路思路（流式分块 + RMS 静音过滤 + 悬浮字幕）沿用原设计。

语音识别使用 [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)。

> 本项目与微信官方无关。不注入、不 Hook 微信进程，仅通过 macOS 公开音频 API 捕获音频。
> 请在对方知情同意的前提下使用。
