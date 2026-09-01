# 🎙️ wechat-live-caption-mac · 微信通话实时字幕（macOS）

> 独立仓库（含 issue / release）：https://github.com/Mindse-Tt/wechat-live-caption-mac

> 给 macOS 微信语音/视频通话加**实时中文字幕**，而且**只抓微信一个 App 的声音**。
> 不用装虚拟声卡，不用付费工具，全程本地推理，约 400MB。
>
> Real-time Chinese captions for WeChat calls on macOS. Per-app audio capture via
> Core Audio Process Tap — no virtual sound card, no paid tools, fully offline.

## 它解决什么 · Why

Windows 上有现成方案：装 VB-CABLE 虚拟声卡，再去音量混合器把微信的输出设备单独指过去，程序只听这一条通道。**macOS 压根没有「给单个 App 指定输出设备」这个功能**，微信 Mac 版自己也没有，照搬直接断路。

这个版本改用 macOS 14.4 新增的 **Core Audio Process Tap**，直接对微信进程的音频输出打点。能力等价，而且更干净：不装驱动、不改任何音频设置、不重启，微信照常从你耳机出声。

顺手做了三件原版没有的事：**说话人区分**（对方 / 我 两行分开）、**回声抑制**（没戴耳机也不串音）、**通话自动开关**。体积从约 3GB 压到约 400MB。

## 快速用 · Quick start

```bash
git clone https://github.com/Mindse-Tt/wechat-live-caption-mac.git
cd wechat-live-caption-mac
./install.sh
```

然后**双击 `微信实时字幕.app`**，点「开始」。

> ⚠️ **必须走 `.app`，不能用 `./start.sh`。**
> 命令行里的 python 没有独立的 TCC 身份，拿不到「系统音频录制」授权，
> 而 macOS 对未授权的 tap 是**静默返回全零**——不报错，就是没字幕。

首次运行会弹授权框，点允许。没弹的话手动开
`系统设置 → 隐私与安全性 → 屏幕与系统音频录制`，**开完要完全退出程序再重开**。

## 核心方法 · The method

```
对方说话 ──→ 微信输出 ──→ Process Tap ──┐
                                        ├──→ 同一个模型，两个 stream ──→ 悬浮字幕
我说话   ──→ 麦克风    ──→ 回声抑制  ──┘
```

**说话人区分不靠声纹模型。** 这两路音频物理上本来就是分开的：对方的声音只可能来自微信输出，我的声音只可能来自麦克风。两路分开采、各自识别、各自打标签，100% 准确，不存在认错人。声纹聚类在真实通话里会被抢话、音色接近、背景噪声干扰，这个方案一个都碰不到。

**回声抑制靠音量，不是靠波形。** 没戴耳机时对方的声音会从扬声器漏回麦克风。

第一版我用归一化互相关判断——回声是同一句话，波形应该也一样。离线测下来区分度极高（回声 53 倍，我说话 8–21 倍）。**拿真实录音一测直接失效**：真回声相关度 0.24，完全不相干的语音 0.28，不但没区分度还反了。根因是我的测试数据是拿原信号乘系数造的，而真实回声过了扬声器和麦克风的频响、还有房间混响，波形早变了。

现在改成看音量。实测绕一圈的衰减：对方原声 0.128，回声 0.035，约四分之一。程序自适应估计这个衰减比（实测学到 0.24，真值 0.27），只有明显超过这个水平的声音才算是你在说话。

| 场景 | 结果 |
|---|---|
| 回声块 | 拦掉 93.5% |
| 我单独说话 | 误杀 0% |
| 双讲（我 + 对方） | 误杀 4.2% |

代价是双讲时偶尔丢一两个字，戴耳机则完全没有这个问题。

**通话检测靠麦克风占用。** 查微信进程的 `kAudioProcessPropertyIsRunningInput`。放语音消息只占扬声器，只有真通话才占麦克风，信号很干净。

## 关键实现 · Key details

| 步骤 | API / 做法 |
|---|---|
| 找到微信进程 | `kAudioHardwarePropertyProcessObjectList` 枚举，按 bundle id 过滤 |
| 建立 tap | `AudioHardwareCreateProcessTap` + `CATapDescription` |
| 不打断通话 | `muteBehavior = 0`，声音照常从耳机出 |
| 包成可读设备 | 私有聚合设备，**`master` 必须指向真实输出设备** |
| 读取音频 | 聚合设备就是普通输入设备，PortAudio 直接开 |
| 语音识别 | sherpa-onnx 流式 zipformer（int8，自带标点，支持中英混说） |

## 硬规则（踩坑总结）· Hard rules

1. **必须打包成 .app**。命令行 python 没有 TCC 身份，系统不会弹授权框。
2. **授权不通 = 静音，不是报错**。查了半天代码才发现是权限问题。
3. **聚合设备没有时钟源 = 静音**。`master` 不指真实输出设备，症状跟第 2 条一模一样。
4. **测试数据别自己造**。回声抑制第一版就栽在这：合成数据上完美，真实录音上归零。
5. **中途换耳机要重启程序**。聚合设备的时钟设备在启动时锁定。
6. **微信必须先出过声**，否则不在音频进程列表里，找不到它。

## 常用命令 · CLI

```bash
./start.sh --apps          # 列出当前所有有音频的 App
./start.sh --app 13318     # 抓别的 App（bundle id 片段或 PID 都行）
./start.sh --mic           # 只识别自己说的话
./start.sh --list          # 列出音频输入设备
```

注意：命令行方式同样受权限限制，正式使用还是走 `.app`。

## 已知限制 · Limitations

- **群语音分不出人**：3 人以上时「对方」那一路是混音，要分需要声纹聚类模型。
- **延迟约 1 秒**：当前用 960ms 分块模型。仓库支持换 480ms 版本，更跟手但准确率略降。
- **只支持 macOS 14.4+**：Process Tap 是这个版本才有的 API。

## 致谢 · Credits

移植自 [cengyingte-stack](https://github.com/cengyingte-stack) 的 Windows 版本，
识别链路思路（流式分块 + RMS 静音过滤 + 悬浮字幕）沿用原设计。

语音识别使用 [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)。

> 本项目与微信官方无关。不注入、不 Hook 微信进程，仅通过 macOS 公开音频 API 捕获音频。
> 全程本地推理，不保存音频文件，不上传任何数据。**请在对方知情同意的前提下使用。**

## License

MIT © 2026 许惟 / Mindse-Tt

—
做这个的人：**惟见 AI** ｜在大厂做 AI 产品，只分享真在用的东西。
