# -*- coding: utf-8 -*-
"""自检：判断「系统音频录制」权限到底有没有生效。

做法：自己播一段测试音，同时开一个全局 tap 去抓。
抓到波形 = 权限通了；全是 0 = 权限没通。
不需要微信正在通话，结论不含糊。
"""
import os, sys, time, uuid, wave, queue, subprocess
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def log(*a): print(*a, flush=True)

log("=" * 52)
log("微信实时字幕 · 权限自检")
log("=" * 52)
log(f"运行身份 PID={os.getpid()}  父进程={os.getppid()}")

# 1. 微信在不在
try:
    import apptap
    procs = apptap.list_audio_processes()
    wx = [p for p in procs if p[2] and "xinwechat" in p[2].lower()]
    log(f"\n[1] 系统音频进程共 {len(procs)} 个")
    if wx:
        for o, p, b in wx:
            log(f"    ✓ 找到微信: PID={p} bundle={b}")
    else:
        log("    ✗ 没找到微信音频进程")
        log("      -> 请打开微信，并让它出一次声(收条语音/进通话)")
except Exception as e:
    log(f"[1] 失败: {e}"); raise SystemExit(2)

# 2. 造一段测试音
tone_path = "/tmp/_caption_doctor_tone.wav"
sr = 44100; dur = 6.0
t = np.arange(int(sr * dur)) / sr
wav = (0.35 * np.sin(2 * np.pi * 440 * t) * np.hanning(len(t))**0.2).astype(np.float32)
with wave.open(tone_path, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes((wav * 32767).astype(np.int16).tobytes())
log(f"\n[2] 已生成 {dur:.0f} 秒测试音")

# 3. 建全局 tap
import objc
from ctypes import c_uint32, byref
from Foundation import NSDictionary, NSArray
CATap = objc.lookUpClass("CATapDescription"); NSUUID = objc.lookUpClass("NSUUID")
d = CATap.alloc().initStereoGlobalTapButExcludeProcesses_(NSArray.array())
d.setName_("CaptionDoctor"); d.setPrivate_(True); d.setMuteBehavior_(0)
d.setUUID_(NSUUID.alloc().initWithUUIDString_(str(uuid.uuid4())))
tap = c_uint32()
st = apptap._ca.AudioHardwareCreateProcessTap(objc.pyobjc_id(d), byref(tap))
log(f"[3] 创建全局 tap: status={st} tapID={tap.value}")
if st != 0:
    log("    ✗ tap 创建失败"); raise SystemExit(3)

out_uid = apptap.default_output_uid()
agg_name = "CaptionDoctorAgg"
dd = NSDictionary.dictionaryWithDictionary_({
    "name": agg_name, "uid": str(uuid.uuid4()), "private": 1, "stacked": 0,
    "tapautostart": 1, "master": out_uid, "subdevices": [],
    "taps": [{"uid": apptap._get_str(tap.value, "tuid"), "drift": 1}]})
agg = c_uint32()
st = apptap._ca.AudioHardwareCreateAggregateDevice(objc.pyobjc_id(dd), byref(agg))
log(f"    聚合设备: status={st}  时钟={out_uid}")

# 4. 一边放音一边抓
import sounddevice as sd
sd._terminate(); sd._initialize()
idx = ch = None
for i, dv in enumerate(sd.query_devices()):
    if dv["max_input_channels"] > 0 and dv["name"] == agg_name:
        idx, ch = i, min(2, dv["max_input_channels"]); break
if idx is None:
    log("    ✗ PortAudio 看不到聚合设备"); raise SystemExit(4)

log(f"\n[4] 开始抓取(会听到 6 秒提示音)…")
player = subprocess.Popen(["afplay", tone_path])
q = queue.Queue(); peak = 0.0; nz = 0; total = 0
with sd.InputStream(device=idx, channels=ch, samplerate=48000, dtype="float32",
                    blocksize=4800, callback=lambda a, b, c, e: q.put(a.copy())):
    t0 = time.time()
    while time.time() - t0 < 7:
        try: b = q.get(timeout=0.5)
        except queue.Empty: continue
        total += 1
        m = float(np.max(np.abs(b)))
        if m > 0: nz += 1
        peak = max(peak, m)
player.wait()
apptap._ca.AudioHardwareDestroyAggregateDevice(agg.value)
apptap._ca.AudioHardwareDestroyProcessTap(tap.value)

log(f"    采集块数={total}  非零块={nz}  峰值={peak:.5f}")
log("\n" + "=" * 52)
if peak > 0.001:
    log("结论：✅ 权限已生效，tap 能拿到声音")
    log("      现在可以直接打微信电话用了。")
else:
    log("结论：❌ 权限没生效，tap 只拿到静音")
    log("")
    log("请手动开启：")
    log("  系统设置 → 隐私与安全性 → 屏幕与系统音频录制")
    log("  找到「微信实时字幕」，把开关打开")
    log("  然后完全退出本程序，再重新双击 .app")
log("=" * 52)
