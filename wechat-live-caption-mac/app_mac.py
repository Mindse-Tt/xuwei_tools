# -*- coding: utf-8 -*-
"""
微信实时字幕 · macOS 版 v2

在 v1(移植 Windows 原版)基础上加了三件事：
  1. 双路识别 —— 对方走 Core Audio tap，自己走麦克风，两路物理隔离，
     说话人区分 100% 准确，不需要声纹模型去猜。
  2. 控制台 —— 一个窗口，点按钮开始/停止，不用记命令。
  3. 自动模式 —— 检测到微信占用麦克风(=进入通话)就自动开字幕，挂断自动停。
"""
import os
import sys
import glob
import time
import queue
import argparse
import threading
import tkinter as tk

import re
from collections import deque

import numpy as np
import sounddevice as sd
import sherpa_onnx

import apptap

TARGET_RATE = 16000
BLOCK_SEC = 0.2
RMS_GATE = 0.0025
MAX_SHOWN = 60
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_ROOT = os.path.join(HERE, "models")

BG, FG, SUB = "#1e1e21", "#f2f2f4", "#9a9aa2"
OK, BAD, WARN = "#4ade80", "#f87171", "#fbbf24"


# ------------------------------------------------------------------ 模型

_CJK = "\u4e00-\u9fff\u3000-\u303f\uff00-\uffef"
_RE_WS = re.compile(r"\s+")
_RE_CJK_GAP = re.compile(f"(?<=[{_CJK}])\\s+(?=[{_CJK}])")
_RE_PUNCT_GAP = re.compile(r"\s+([，。！？、；：,.!?;:])")


def tidy(t):
    """流式模型按 BPE 出字，中文之间会夹空格，这里清理成正常中文排版。"""
    t = _RE_WS.sub(" ", t).strip()
    t = _RE_CJK_GAP.sub("", t)
    t = _RE_PUNCT_GAP.sub(r"\1", t)
    return t


REF_KEEP = TARGET_RATE * 2          # 保留最近 2 秒的对方音频做参考
ECHO_PEAK = 0.55                    # 峰值门限
ECHO_RATIO = 4.0                    # 峰值要比背景中位数高这么多倍


def echo_score(x, ref):
    """判断麦克风这一块声音是不是扬声器漏回来的对方声音。

    对方的声音从扬声器出来又被麦克风收进去，波形是同一个，只是延迟+衰减。
    做归一化互相关，真回声会在某个延迟上出现一个又高又尖的峰；
    而你自己说话跟对方的声音无关，相关曲线是平的。
    所以判据不是「峰有多高」，是「峰比背景突出多少」——
    只看绝对值会把无关语音也误杀（实测随机语音也能撞到 0.5）。

    返回 (峰值, 峰背比)。
    """
    n = len(x)
    if n < 256:
        return 0.0, 0.0
    x0 = x - x.mean()
    xn = float(np.linalg.norm(x0))
    if xn < 1e-6:
        return 0.0, 0.0
    # 只在合理的回声延迟范围内找（0~400ms），缩小搜索面能大幅降低误判
    span = n + int(TARGET_RATE * 0.4)
    r = ref[-span:]
    m = len(r)
    lags = m - n + 1
    if lags < 16:
        return 0.0, 0.0
    N = 1 << (m + n - 1).bit_length()
    cc = np.fft.irfft(np.fft.rfft(r, N) * np.conj(np.fft.rfft(x0, N)), N)[:lags]
    cs = np.concatenate(([0.0], np.cumsum(r.astype(np.float64) ** 2)))
    win = np.sqrt(np.maximum(cs[n:n + lags] - cs[:lags], 1e-12))
    ncc = np.abs(cc) / (win * xn + 1e-12)
    peak = float(np.max(ncc))
    base = float(np.median(ncc)) + 1e-9
    return peak, peak / base


def is_echo(x, ref):
    if len(ref) < len(x) + 64:
        return False
    peak, ratio = echo_score(x, ref)
    return peak > ECHO_PEAK and ratio > ECHO_RATIO


def find_model_dir(prefer_punct=True):
    cands = [c for c in sorted(glob.glob(os.path.join(MODEL_ROOT, "sherpa-onnx-*")))
             if os.path.isdir(c)]
    if not cands:
        raise RuntimeError("models/ 下没有模型，请先运行 ./install.sh")
    if prefer_punct:
        punct = [c for c in cands if "punct" in os.path.basename(c)]
        if punct:
            return punct[0]
    return cands[0]


def _pick(d, pat):
    hits = sorted(glob.glob(os.path.join(d, pat)))
    hits.sort(key=lambda p: (0 if "int8" in p else 1, len(p)))
    return hits[0] if hits else None


def build_recognizer(model_dir, threads=2):
    tokens = _pick(model_dir, "tokens.txt")
    enc = _pick(model_dir, "encoder*.onnx")
    dec = _pick(model_dir, "decoder*.onnx")
    joi = _pick(model_dir, "joiner*.onnx")
    if not tokens or not enc:
        raise RuntimeError(f"模型目录不完整: {model_dir}")
    common = dict(tokens=tokens, num_threads=threads, sample_rate=TARGET_RATE,
                  feature_dim=80, enable_endpoint_detection=True,
                  rule1_min_trailing_silence=2.4, rule2_min_trailing_silence=1.2,
                  rule3_min_utterance_length=300,
                  decoding_method="greedy_search", provider="cpu")
    if joi and dec:
        return sherpa_onnx.OnlineRecognizer.from_transducer(
            encoder=enc, decoder=dec, joiner=joi, **common)
    return sherpa_onnx.OnlineRecognizer.from_zipformer2_ctc(model=enc, **common)


# ------------------------------------------------------------------ 音频

def list_inputs():
    return [(i, d["name"], d["max_input_channels"], int(d["default_samplerate"]))
            for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]


def find_device(want):
    for i, n, c, r in list_inputs():
        if want == n:
            return i, n, c, r
    for i, n, c, r in list_inputs():
        if str(want).lower() in n.lower():
            return i, n, c, r
    return None


def default_mic():
    di = sd.default.device[0]
    for i, n, c, r in list_inputs():
        if i == di:
            return i, n, c, r
    ins = list_inputs()
    return ins[0] if ins else None


def to_mono_16k(block, src_rate):
    x = np.asarray(block, dtype=np.float32)
    x = x.mean(axis=1) if x.ndim > 1 and x.shape[1] > 1 else x.reshape(-1)
    if src_rate != TARGET_RATE:
        n = int(round(len(x) * TARGET_RATE / src_rate))
        if n <= 0:
            return np.empty(0, dtype=np.float32)
        x = np.interp(np.linspace(0, len(x) - 1, n),
                      np.arange(len(x)), x).astype(np.float32)
    return x


def wechat_in_call():
    """微信是否正在通话 —— 靠它有没有占用麦克风来判断。
    放语音消息只占扬声器不占麦，只有语音/视频通话才会占麦。"""
    from ctypes import c_uint32, byref
    for oid, pid, bid in apptap.list_audio_processes():
        if bid and "xinwechat" in bid.lower():
            v = c_uint32()
            if apptap._get(oid, "piri", byref(v), 4) == 0 and v.value:
                return True
    return False


class Source(threading.Thread):
    """一路音频源：不停地把 16k 单声道数据打上标签丢进共享队列。"""

    def __init__(self, tag, dev_idx, ch, rate, out_q, stop_event):
        super().__init__(daemon=True)
        self.tag, self.dev_idx, self.ch, self.rate = tag, dev_idx, ch, rate
        self.out_q, self.stop_event = out_q, stop_event
        self.error = None
        self.saw_signal = False

    def run(self):
        try:
            q = queue.Queue(maxsize=64)

            def cb(indata, frames, t, status):
                try:
                    q.put_nowait(indata.copy())
                except queue.Full:
                    pass

            with sd.InputStream(device=self.dev_idx, channels=self.ch,
                                samplerate=self.rate, dtype="float32",
                                blocksize=int(self.rate * BLOCK_SEC), callback=cb):
                while not self.stop_event.is_set():
                    try:
                        b = q.get(timeout=0.3)
                    except queue.Empty:
                        continue
                    m = to_mono_16k(b, self.rate)
                    if len(m) == 0:
                        continue
                    if not self.saw_signal and float(np.max(np.abs(m))) > 0:
                        self.saw_signal = True
                    self.out_q.put((self.tag, m))
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"


class Engine(threading.Thread):
    """识别引擎：一个模型，多路 stream，各路独立出字幕。"""

    def __init__(self, ui, mode, use_mic, threads=2, aec=True):
        super().__init__(daemon=True)
        self.ui, self.mode, self.use_mic, self.threads = ui, mode, use_mic, threads
        self.aec = aec              # 是否做回声抑制
        self.echo_drops = 0
        self.stop_event = threading.Event()
        self.tap = None
        self.sources = []

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            self.ui.post("status", "正在加载识别模型…")
            rec = build_recognizer(find_model_dir(), self.threads)
            shared = queue.Queue()
            desc = []

            # --- 对方这一路：Core Audio tap
            if self.mode in ("wechat", "global"):
                self.tap = apptap.AppTap(
                    None if self.mode == "global" else "xinWeChat",
                    label="WeChatCaption",
                    use_global=(self.mode == "global"))
                name = self.tap.start()
                sd._terminate(); sd._initialize()
                found = find_device(name)
                if not found:
                    raise RuntimeError("PortAudio 看不到 tap 设备")
                i, n, c, r = found
                self.sources.append(Source("对方", i, min(2, c), r,
                                           shared, self.stop_event))
                if self.mode == "wechat":
                    pids = ", ".join(str(p) for _, p, _ in self.tap.targets)
                    desc.append(f"对方=微信(PID {pids})")
                else:
                    desc.append("对方=全部系统声音")

            # --- 我这一路：麦克风
            if self.use_mic or self.mode == "mic":
                m = default_mic()
                if m:
                    i, n, c, r = m
                    self.sources.append(Source("我", i, min(1, c) or 1, r,
                                               shared, self.stop_event))
                    desc.append(f"我={n}")

            if not self.sources:
                raise RuntimeError("没有任何可用的音频源")

            for s in self.sources:
                s.start()
            self.ui.post("status", " | ".join(desc))
            self.ui.post("running", True)

            streams = {s.tag: rec.create_stream() for s in self.sources}
            hist = {s.tag: deque(maxlen=3) for s in self.sources}
            t0 = time.time()
            warned = False
            reported = set()
            ref = np.zeros(0, dtype=np.float32)   # 最近的对方音频

            while not self.stop_event.is_set():
                for s in self.sources:
                    if s.error and s.tag not in reported:
                        reported.add(s.tag)
                        self.ui.post("status", f"[{s.tag}] 这一路失败：{s.error}")
                if all(s.error for s in self.sources):
                    raise RuntimeError("所有音频源都失败了：" +
                                       "; ".join(f"{s.tag}={s.error}" for s in self.sources))
                try:
                    tag, mono = shared.get(timeout=0.3)
                except queue.Empty:
                    tag = None

                # 权限自检：tap 那路 10 秒还全是 0 → 多半没授权
                if (not warned and self.tap and time.time() - t0 > 10
                        and not any(s.saw_signal for s in self.sources
                                    if s.tag == "对方")):
                    warned = True
                    self.ui.post("caption", ("对方", "⚠️ 拿不到声音，缺「系统音频录制」权限"))
                    self.ui.post("status",
                                 "系统设置 → 隐私与安全性 → 屏幕与系统音频录制 → 打开本程序，然后重开")

                if tag is None:
                    continue
                if float(np.sqrt(np.mean(mono ** 2) + 1e-12)) < RMS_GATE:
                    if tag == "对方":
                        ref = np.concatenate((ref, mono))[-REF_KEEP:]
                    continue

                if tag == "对方":
                    ref = np.concatenate((ref, mono))[-REF_KEEP:]
                elif self.aec and len(ref) > TARGET_RATE // 2:
                    # 这块麦克风声音是不是扬声器漏回来的对方声音
                    if is_echo(mono, ref):
                        self.echo_drops += 1
                        continue

                st = streams[tag]
                st.accept_waveform(TARGET_RATE, mono)
                while rec.is_ready(st):
                    rec.decode_stream(st)
                txt = tidy(rec.get_result(st))
                if rec.is_endpoint(st):
                    if txt:
                        hist[tag].append(txt)   # 一句说完，收进历史
                    rec.reset(st)
                    txt = ""
                lines = list(hist[tag]) + ([txt] if txt else [])
                if lines:
                    self.ui.post("caption", (tag, "\n".join(lines[-2:])))

        except Exception as e:
            self.ui.post("fatal", f"{type(e).__name__}: {e}")
        finally:
            if self.tap:
                self.tap.stop()
            self.ui.post("running", False)


# ------------------------------------------------------------------ 字幕窗

class Overlay(tk.Toplevel):
    """字幕悬浮窗。支持四种摆位：底部横条 / 右侧竖条 / 左侧竖条 / 贴着微信窗口。"""

    LAYOUTS = {
        "bottom": (940, 230),
        "right": (430, 620),
        "left": (430, 620),
        "follow": (430, 620),
    }

    def __init__(self, master, font_size=26, layout="bottom"):
        super().__init__(master)
        self.font_size = font_size
        self.layout = layout
        self.drag = None
        self.pinned = False          # 用户手动拖过就不再自动跟随

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.93)
        self.configure(bg="#000000")

        w, h = self.LAYOUTS.get(layout, self.LAYOUTS["bottom"])
        self.w, self.h = w, h
        side = layout != "bottom"

        self.lines = {}
        for tag, color in (("对方", "#ffffff"), ("我", "#7dd3fc")):
            fr = tk.Frame(self, bg="#111114")
            fr.pack(fill="both", expand=True, padx=8, pady=3)
            head = tk.Frame(fr, bg="#111114")
            head.pack(fill="x", anchor="w")
            tk.Label(head, text=tag, bg="#111114",
                     fg="#fbbf24" if tag == "对方" else "#7dd3fc",
                     font=("PingFang SC", 12, "bold")
                     ).pack(side="left", padx=(12, 0), pady=(8, 0))
            size = font_size if tag == "对方" else font_size - 4
            lb = tk.Label(fr, text="", bg="#111114", fg=color, justify="left",
                          anchor="nw", wraplength=w - 40,
                          font=("PingFang SC", size), padx=12, pady=6)
            lb.pack(fill="both", expand=True)
            self.lines[tag] = lb

        self.status = tk.Label(self, text="", bg="#000000", fg=SUB,
                               font=("PingFang SC", 10), wraplength=w - 20)
        self.status.pack(fill="x", pady=(0, 5))

        for wdg in [self, self.status] + list(self.lines.values()):
            wdg.bind("<ButtonPress-1>", self.press)
            wdg.bind("<B1-Motion>", self.move_)

        self.place_window()
        if layout == "follow":
            self.after(1200, self.follow_tick)

    # -- 摆位
    def place_window(self):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.w, self.h
        if self.layout == "bottom":
            x, y = (sw - w) // 2, sh - h - 110
        elif self.layout == "left":
            x, y = 30, (sh - h) // 2
        else:                       # right / follow 初始
            x, y = sw - w - 30, (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def wechat_window(self):
        """找微信最大的那个窗口（通话窗），返回 (x, y, w, h)。"""
        try:
            import Quartz
            wl = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly
                | Quartz.kCGWindowListExcludeDesktopElements,
                Quartz.kCGNullWindowID)
            best = None
            for win in wl:
                own = win.get("kCGWindowOwnerName", "") or ""
                if "WeChat" not in own and "微信" not in own:
                    continue
                b = win.get("kCGWindowBounds", {})
                bw, bh = int(b.get("Width", 0)), int(b.get("Height", 0))
                if bw < 300 or bh < 200:       # 跳过菜单栏图标之类的小窗
                    continue
                if best is None or bw * bh > best[2] * best[3]:
                    best = (int(b.get("X", 0)), int(b.get("Y", 0)), bw, bh)
            return best
        except Exception:
            return None

    def follow_tick(self):
        """贴着微信窗口：优先放右边，右边放不下就放左边。"""
        if not self.winfo_exists():
            return
        if not self.pinned:
            box = self.wechat_window()
            if box:
                wx, wy, ww, wh = box
                sw = self.winfo_screenwidth()
                gap = 12
                if wx + ww + gap + self.w <= sw:
                    x = wx + ww + gap
                else:
                    x = max(10, wx - gap - self.w)
                y = max(10, min(wy, self.winfo_screenheight() - self.h - 10))
                self.geometry(f"{self.w}x{self.h}+{x}+{y}")
        self.after(1500, self.follow_tick)

    # -- 拖动
    def press(self, e):
        self.pinned = True          # 手动拖过就停止自动跟随
        self.drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def move_(self, e):
        if self.drag:
            self.geometry(f"+{e.x_root-self.drag[0]}+{e.y_root-self.drag[1]}")

    def set_line(self, tag, text):
        if tag in self.lines:
            self.lines[tag].config(text=text)

    def font_step(self, d):
        self.font_size = max(13, min(46, self.font_size + d))
        self.lines["对方"].config(font=("PingFang SC", self.font_size))
        self.lines["我"].config(font=("PingFang SC", max(11, self.font_size - 4)))


# ------------------------------------------------------------------ 控制台

class Console:
    def __init__(self, args):
        self.args = args
        self.engine = None
        self.overlay = None
        self.q = queue.Queue()
        self.auto_started = False    # 这次是不是自动模式拉起来的

        r = tk.Tk()
        self.root = r
        r.title("微信实时字幕")
        r.configure(bg=BG)
        r.resizable(False, False)
        w, h = 470, 600
        r.geometry(f"{w}x{h}+{(r.winfo_screenwidth()-w)//2}"
                   f"+{(r.winfo_screenheight()-h)//3}")

        tk.Label(r, text="微信实时字幕", bg=BG, fg=FG,
                 font=("PingFang SC", 22, "bold")).pack(pady=(20, 0))
        tk.Label(r, text="对方走系统音频，自己走麦克风，两路分开识别", bg=BG, fg=SUB,
                 font=("PingFang SC", 11)).pack(pady=(2, 0))

        card = tk.Frame(r, bg="#28282c")
        card.pack(fill="x", padx=22, pady=(16, 4))
        self.rows = {}
        for k, lab in (("wechat", "微信"), ("call", "通话状态"), ("model", "识别模型")):
            row = tk.Frame(card, bg="#28282c")
            row.pack(fill="x", padx=14, pady=6)
            dot = tk.Label(row, text="●", bg="#28282c", fg=SUB, font=("PingFang SC", 12))
            dot.pack(side="left")
            tk.Label(row, text=lab, bg="#28282c", fg=FG,
                     font=("PingFang SC", 12)).pack(side="left", padx=(8, 0))
            val = tk.Label(row, text="…", bg="#28282c", fg=SUB, font=("PingFang SC", 11))
            val.pack(side="right")
            self.rows[k] = (dot, val)

        mf = tk.Frame(r, bg=BG)
        mf.pack(fill="x", padx=22, pady=(10, 0))
        tk.Label(mf, text="听哪一路", bg=BG, fg=SUB,
                 font=("PingFang SC", 11)).pack(anchor="w")
        self.mode = tk.StringVar(value="wechat")
        for v, t in (("wechat", "只听微信（推荐）"),
                     ("global", "所有系统声音（兜底）"),
                     ("mic", "只听麦克风")):
            tk.Radiobutton(mf, text=t, variable=self.mode, value=v, bg=BG, fg=FG,
                           selectcolor="#28282c", activebackground=BG,
                           activeforeground=FG, highlightthickness=0,
                           font=("PingFang SC", 12)).pack(anchor="w")
        self.dual = tk.BooleanVar(value=True)
        tk.Checkbutton(mf, text="同时识别我自己的声音（双路分说话人）",
                       variable=self.dual, bg=BG, fg=FG, selectcolor="#28282c",
                       activebackground=BG, activeforeground=FG,
                       highlightthickness=0, font=("PingFang SC", 12)
                       ).pack(anchor="w", pady=(6, 0))
        pf = tk.Frame(mf, bg=BG)
        pf.pack(fill="x", pady=(8, 2))
        tk.Label(pf, text="字幕放哪", bg=BG, fg=SUB,
                 font=("PingFang SC", 11)).pack(anchor="w")
        self.pos = tk.StringVar(value="follow")
        prow = tk.Frame(pf, bg=BG)
        prow.pack(fill="x")
        for v, t in (("follow", "贴着微信窗口"), ("right", "屏幕右侧"),
                     ("left", "屏幕左侧"), ("bottom", "屏幕底部")):
            tk.Radiobutton(prow, text=t, variable=self.pos, value=v, bg=BG, fg=FG,
                           selectcolor="#28282c", activebackground=BG,
                           activeforeground=FG, highlightthickness=0,
                           font=("PingFang SC", 11)).pack(side="left")

        self.aec = tk.BooleanVar(value=True)
        tk.Checkbutton(mf, text="回声抑制（没戴耳机时必开）",
                       variable=self.aec, bg=BG, fg=FG, selectcolor="#28282c",
                       activebackground=BG, activeforeground=FG,
                       highlightthickness=0, font=("PingFang SC", 12)
                       ).pack(anchor="w")

        self.auto = tk.BooleanVar(value=False)
        tk.Checkbutton(mf, text="自动模式：微信一进通话就自动开字幕",
                       variable=self.auto, command=self.toggle_auto,
                       bg=BG, fg=FG, selectcolor="#28282c", activebackground=BG,
                       activeforeground=FG, highlightthickness=0,
                       font=("PingFang SC", 12)).pack(anchor="w")

        # macOS 上 tk.Button 会忽略 bg，用 Frame+Label 自己画一个
        self.btn_frame = tk.Frame(r, bg="#3b82f6", cursor="pointinghand")
        self.btn_frame.pack(fill="x", padx=22, pady=(14, 0))
        self.btn = tk.Label(self.btn_frame, text="▶  开始", bg="#3b82f6",
                            fg="white", font=("PingFang SC", 16, "bold"),
                            cursor="pointinghand")
        self.btn.pack(fill="both", expand=True, pady=11)
        for wdg in (self.btn_frame, self.btn):
            wdg.bind("<Button-1>", lambda e: self.toggle())

        self.hint = tk.Label(r, text="", bg=BG, fg=SUB, font=("PingFang SC", 11),
                             wraplength=420, justify="left")
        self.hint.pack(padx=22, pady=(10, 0), anchor="w")

        r.protocol("WM_DELETE_WINDOW", self.quit_all)
        r.bind_all("<Control-Up>", lambda e: self.overlay and self.overlay.font_step(2))
        r.bind_all("<Control-Down>", lambda e: self.overlay and self.overlay.font_step(-2))
        r.after(80, self.pump)
        r.after(200, self.tick)

    # ---- 线程投递
    def post(self, kind, val):
        self.q.put((kind, val))

    def pump(self):
        try:
            while True:
                kind, v = self.q.get_nowait()
                if kind == "row":
                    k, c, t = v
                    self.rows[k][0].config(fg=c)
                    self.rows[k][1].config(text=t, fg=FG if c == OK else SUB)
                elif kind == "autostart":
                    self.start_engine(auto=True) if v else self.stop_engine()
                elif kind == "caption" and self.overlay:
                    self.overlay.set_line(*v)
                elif kind == "status":
                    if self.overlay:
                        self.overlay.status.config(text=v)
                    self.hint.config(text=v)
                elif kind == "fatal":
                    self.hint.config(text=v)
                    self.stop_engine()
                elif kind == "running":
                    col = "#ef4444" if v else "#3b82f6"
                    self.btn.config(text="■  停止" if v else "▶  开始", bg=col)
                    self.btn_frame.config(bg=col)
        except queue.Empty:
            pass
        self.root.after(80, self.pump)

    # ---- 周期检测 + 自动模式
    def tick(self):
        threading.Thread(target=self._probe, daemon=True).start()
        self.root.after(2000, self.tick)

    def _probe(self):
        try:
            wx = [p for p in apptap.list_audio_processes()
                  if p[2] and "xinwechat" in p[2].lower()]
            self.q.put(("row", ("wechat", OK if wx else BAD,
                                f"PID {wx[0][1]}" if wx else "未找到")))
            incall = wechat_in_call()
            self.q.put(("row", ("call", OK if incall else SUB,
                                "通话中" if incall else "空闲")))
            if self.auto.get():
                if incall and not self.engine:
                    self.q.put(("autostart", True))
                # 只收自动模式自己拉起来的那次；手动点开的不碰
                elif not incall and self.engine and self.auto_started:
                    self.q.put(("autostart", False))
        except Exception:
            pass
        try:
            self.q.put(("row", ("model", OK,
                                os.path.basename(find_model_dir())
                                .replace("sherpa-onnx-streaming-", "")[:26])))
        except Exception:
            self.q.put(("row", ("model", BAD, "缺失")))

    def toggle_auto(self):
        self.hint.config(text="自动模式已开：微信一进通话就自动开字幕，挂断自动停。"
                         if self.auto.get() else "")

    # ---- 启停
    def toggle(self):
        self.stop_engine() if self.engine else self.start_engine()

    def start_engine(self, auto=False):
        if self.engine:
            return
        self.auto_started = auto
        self.overlay = Overlay(self.root, self.args.font, self.pos.get())
        mode = self.mode.get()
        self.engine = Engine(self, mode, self.dual.get() and mode != "mic",
                             aec=self.aec.get())
        self.engine.start()

    def stop_engine(self):
        self.auto_started = False
        if self.engine:
            self.engine.stop()
            self.engine = None
        if self.overlay:
            self.overlay.destroy()
            self.overlay = None
        self.btn.config(text="▶  开始", bg="#3b82f6")
        self.btn_frame.config(bg="#3b82f6")

    def quit_all(self):
        self.stop_engine()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ------------------------------------------------------------------ 入口

def main():
    ap = argparse.ArgumentParser(description="微信实时字幕 macOS 版")
    ap.add_argument("--apps", action="store_true", help="列出有音频的 App")
    ap.add_argument("--list", action="store_true", help="列出音频输入设备")
    ap.add_argument("--auto", action="store_true", help="启动即开自动模式")
    ap.add_argument("--font", type=int, default=26)
    args = ap.parse_args()

    if args.apps:
        seen = set()
        for oid, pid, bid in apptap.list_audio_processes():
            if bid and bid not in seen:
                seen.add(bid)
                print(f"  pid={pid:<7} {bid}")
        return
    if args.list:
        for i, n, c, r in list_inputs():
            print(f"  [{i}] {n} ({c}声道/{r}Hz)")
        return

    c = Console(args)
    if args.auto:
        c.auto.set(True)
    c.run()


if __name__ == "__main__":
    main()
