# -*- coding: utf-8 -*-
"""
按 App 抓声音 —— macOS Core Audio Process Tap 封装。

这是 Windows「音量混合器里给微信单独指定输出设备」在 macOS 上的等价物。
macOS 14.4+ 提供 AudioHardwareCreateProcessTap 公开 API, 可以对指定进程的
音频输出打点, 不需要装虚拟声卡驱动, 也不需要付费工具。

流程:
  1. 枚举系统音频进程, 按 bundle id 找到目标 App
  2. 对它建一个 CATapDescription (立体声混合, 不静音 —— 你照常听得见)
  3. AudioHardwareCreateProcessTap 创建 tap
  4. 用一个私有聚合设备把 tap 包起来
  5. 这个聚合设备就是一个普通输入设备, PortAudio/sounddevice 直接读
"""
import uuid
import ctypes
from ctypes import c_uint32, c_int32, c_void_p, byref, POINTER, Structure

import objc
from Foundation import NSDictionary, NSArray, NSNumber

_ca = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")

kAudioObjectSystemObject = 1


def _fcc(s):
    return int.from_bytes(s.encode(), "big")


class _Addr(Structure):
    _fields_ = [("sel", c_uint32), ("scope", c_uint32), ("elem", c_uint32)]


_GLOB = _fcc("glob")

_ca.AudioObjectGetPropertyData.argtypes = [
    c_uint32, POINTER(_Addr), c_uint32, c_void_p, POINTER(c_uint32), c_void_p]
_ca.AudioObjectGetPropertyDataSize.argtypes = [
    c_uint32, POINTER(_Addr), c_uint32, c_void_p, POINTER(c_uint32)]
_ca.AudioHardwareCreateProcessTap.argtypes = [c_void_p, POINTER(c_uint32)]
_ca.AudioHardwareDestroyProcessTap.argtypes = [c_uint32]
_ca.AudioHardwareCreateAggregateDevice.argtypes = [c_void_p, POINTER(c_uint32)]
_ca.AudioHardwareDestroyAggregateDevice.argtypes = [c_uint32]


def _get(oid, sel, buf, size):
    a = _Addr(_fcc(sel), _GLOB, 0)
    sz = c_uint32(size)
    st = _ca.AudioObjectGetPropertyData(oid, byref(a), 0, None, byref(sz), buf)
    return st


def _get_size(oid, sel):
    a = _Addr(_fcc(sel), _GLOB, 0)
    sz = c_uint32(0)
    st = _ca.AudioObjectGetPropertyDataSize(oid, byref(a), 0, None, byref(sz))
    return 0 if st else sz.value


def _get_str(oid, sel):
    p = c_void_p()
    if _get(oid, sel, byref(p), 8) != 0 or not p.value:
        return None
    try:
        return str(objc.objc_object(c_void_p=p))
    except Exception:
        return None


def default_output_uid():
    """默认输出设备的 UID —— 聚合设备需要它来提供时钟。"""
    dev = c_uint32()
    if _get(kAudioObjectSystemObject, "dOut", byref(dev), 4) != 0:
        return None
    return _get_str(dev.value, "uid ")


def list_audio_processes():
    """返回 [(objID, pid, bundle_id)]，即系统里所有用过音频的进程。"""
    size = _get_size(kAudioObjectSystemObject, "prs#")
    if not size:
        return []
    n = size // 4
    arr = (c_uint32 * n)()
    if _get(kAudioObjectSystemObject, "prs#", arr, size) != 0:
        return []
    out = []
    for oid in arr:
        pid = c_int32()
        _get(oid, "ppid", byref(pid), 4)
        out.append((oid, pid.value, _get_str(oid, "pbid")))
    return out


class AppTap:
    """对某个 App 的音频输出建 tap，暴露成一个可被 sounddevice 打开的输入设备。"""

    def __init__(self, match="xinWeChat", label="AppCaption", use_global=False):
        self.match = match
        self.use_global = use_global
        self.label = label
        self.tap_id = None
        self.agg_id = None
        self.device_name = None
        self.targets = []

    def start(self):
        if self.use_global:
            return self._start_global()
        allp = list_audio_processes()
        if str(self.match).isdigit():          # 按 PID 精确匹配
            want = int(self.match)
            procs = [p for p in allp if p[1] == want]
        else:                                   # 按 bundle id 片段匹配
            procs = [p for p in allp
                     if p[2] and self.match.lower() in p[2].lower()]
        if not procs:
            raise RuntimeError(
                f"没有找到匹配 “{self.match}” 的音频进程。\n"
                f"请确认目标 App 已经启动、并且至少播放过一次声音。"
            )
        self.targets = procs

        CATapDescription = objc.lookUpClass("CATapDescription")
        NSUUID = objc.lookUpClass("NSUUID")
        oids = NSArray.arrayWithArray_(
            [NSNumber.numberWithUnsignedInt_(o) for o, _, _ in procs])

        desc = CATapDescription.alloc().initStereoMixdownOfProcesses_(oids)
        desc.setName_(self.label)
        desc.setPrivate_(True)
        # 0 = 不静音：声音照常从你的扬声器/耳机出来，你听得见对方说话
        desc.setMuteBehavior_(0)
        desc.setUUID_(NSUUID.alloc().initWithUUIDString_(str(uuid.uuid4())))

        tap = c_uint32()
        st = _ca.AudioHardwareCreateProcessTap(objc.pyobjc_id(desc), byref(tap))
        if st != 0:
            raise RuntimeError(
                f"创建 process tap 失败 (OSStatus={st})。\n"
                f"如果是 -4 / 权限相关，请到 系统设置 → 隐私与安全性 → 麦克风\n"
                f"给运行本程序的终端 App 打开权限。"
            )
        self.tap_id = tap.value

        tap_uid = _get_str(self.tap_id, "tuid")
        self.device_name = f"{self.label}Agg"
        out_uid = default_output_uid()
        if not out_uid:
            self.stop()
            raise RuntimeError("拿不到默认输出设备 UID，无法为 tap 提供时钟。")
        d = NSDictionary.dictionaryWithDictionary_({
            "name": self.device_name,
            "uid": str(uuid.uuid4()),
            "private": 1,
            "stacked": 0,
            "tapautostart": 1,
            # master 必须指向真实输出设备，否则聚合设备没有时钟、只会吐静音
            "master": out_uid,
            "subdevices": [],
            "taps": [{"uid": tap_uid, "drift": 1}],
        })
        agg = c_uint32()
        st = _ca.AudioHardwareCreateAggregateDevice(objc.pyobjc_id(d), byref(agg))
        if st != 0:
            self.stop()
            raise RuntimeError(f"创建聚合设备失败 (OSStatus={st})")
        self.agg_id = agg.value
        return self.device_name

    def _start_global(self):
        """全局模式：抓所有 App 的声音。
        对应原项目 backup_app.py 抓默认播放设备的做法，作为按 App 抓不到时的兜底。"""
        CATapDescription = objc.lookUpClass("CATapDescription")
        NSUUID = objc.lookUpClass("NSUUID")
        desc = CATapDescription.alloc().initStereoGlobalTapButExcludeProcesses_(
            NSArray.array())
        desc.setName_(self.label)
        desc.setPrivate_(True)
        desc.setMuteBehavior_(0)
        desc.setUUID_(NSUUID.alloc().initWithUUIDString_(str(uuid.uuid4())))
        tap = c_uint32()
        st = _ca.AudioHardwareCreateProcessTap(objc.pyobjc_id(desc), byref(tap))
        if st != 0:
            raise RuntimeError(f"创建全局 tap 失败 (OSStatus={st})")
        self.tap_id = tap.value
        self.targets = [(0, 0, "<全部 App>")]
        return self._make_aggregate(_get_str(self.tap_id, "tuid"))

    def _make_aggregate(self, tap_uid):
        out_uid = default_output_uid()
        if not out_uid:
            self.stop()
            raise RuntimeError("拿不到默认输出设备 UID，无法为 tap 提供时钟。")
        self.device_name = f"{self.label}Agg"
        d = NSDictionary.dictionaryWithDictionary_({
            "name": self.device_name, "uid": str(uuid.uuid4()),
            "private": 1, "stacked": 0, "tapautostart": 1,
            "master": out_uid, "subdevices": [],
            "taps": [{"uid": tap_uid, "drift": 1}],
        })
        agg = c_uint32()
        st = _ca.AudioHardwareCreateAggregateDevice(objc.pyobjc_id(d), byref(agg))
        if st != 0:
            self.stop()
            raise RuntimeError(f"创建聚合设备失败 (OSStatus={st})")
        self.agg_id = agg.value
        return self.device_name

    def stop(self):
        if self.agg_id:
            _ca.AudioHardwareDestroyAggregateDevice(self.agg_id)
            self.agg_id = None
        if self.tap_id:
            _ca.AudioHardwareDestroyProcessTap(self.tap_id)
            self.tap_id = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *a):
        self.stop()
