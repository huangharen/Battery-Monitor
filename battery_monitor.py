"""
Battery Monitor - 电池信息采集模块
使用 psutil + Windows API + WMI 获取全面的电池状态信息
"""

import psutil
import ctypes, time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional


# ─── Windows API 结构 ───────────────────────────────────────────────

class SYSTEM_BATTERY_STATE(ctypes.Structure):
    """CallNtPowerInformation SystemBatteryState (level=5) 返回的结构"""
    _fields_ = [
        ("AcOnLine",       wintypes.BOOLEAN),
        ("BatteryPresent", wintypes.BOOLEAN),
        ("Charging",       wintypes.BOOLEAN),
        ("Discharging",    wintypes.BOOLEAN),
        ("Spare1",         wintypes.BYTE * 4),
        ("MaxCapacity",    wintypes.DWORD),
        ("RemainingCapacity", wintypes.DWORD),
        ("Rate",           ctypes.c_long),     # mW, 正=充电 负=放电
        ("EstimatedTime",  wintypes.DWORD),   # 秒
        ("DefaultAlert1",  wintypes.DWORD),
        ("DefaultAlert2",  wintypes.DWORD),
    ]


# ─── 数据结构 ──────────────────────────────────────────────────────

@dataclass
class BatteryInfo:
    """完整的电池信息"""
    percent:      float           # 电量百分比 0-100
    plugged:      bool            # 是否接通电源
    charging:     bool            # 是否正在充电
    discharging:  bool            # 是否正在放电
    power_rate:   int             # 功率 (mW)
    secsleft:     Optional[int]   # 剩余/充满 预计时间 (秒)
    health:       Optional[float] # 电池健康度百分比
    capacity_mah: Optional[int]   # 电池容量 (毫安时)
    capacity_mwh: Optional[int]   # 电池容量 (毫瓦时)


# ─── 历史电量追踪（用于自力估算充/放电时间） ──────────────────────────

_history: list = []  # [(timestamp, percent), ...]


def _estimate_time_from_history(percent: float, charging: bool) -> Optional[int]:
    """用最近 30 秒内电量变化率线性回归估算充满/剩余时间"""
    global _history
    now = time.time()
    _history.append((now, percent))
    # 只保留最近 30 秒
    _history = [(t, p) for t, p in _history if now - t <= 30]

    if len(_history) < 2:
        return None

    n = len(_history)
    # 简单线性回归: pct = a*t + b, a = slope (%/s)
    sum_t = sum(p[0] for p in _history)
    sum_p = sum(p[1] for p in _history)
    sum_tp = sum(p[0] * p[1] for p in _history)
    sum_tt = sum(p[0] * p[0] for p in _history)

    denom = n * sum_tt - sum_t * sum_t
    if abs(denom) < 0.001:
        return None

    slope = (n * sum_tp - sum_t * sum_p) / denom  # %/s

    if charging:
        if slope <= 0.0005:   # 充电速率太低（涓流或已满）
            return None
        remaining_pct = max(0, 100 - percent)
    else:
        if slope >= -0.0005:  # 放电速率太低
            return None
        remaining_pct = max(0, percent)
        slope = -slope        # 取绝对值

    if slope <= 0:
        return None

    seconds = int(remaining_pct / slope)
    if seconds <= 0 or seconds > 86400 * 2:  # 最多 48 小时
        return None
    return seconds


def _estimate_rate_from_history(charging: bool, capacity_mwh: int = 50000) -> int:
    """从历史电量变化率估算当前功率 mW（需要容量 mWh）"""
    global _history
    now = time.time()
    _history = [(t, p) for t, p in _history if now - t <= 30]
    if len(_history) < 2:
        return 0
    n = len(_history)
    sum_t = sum(p[0] for p in _history)
    sum_p = sum(p[1] for p in _history)
    sum_tp = sum(p[0] * p[1] for p in _history)
    sum_tt = sum(p[0] * p[0] for p in _history)
    denom = n * sum_tt - sum_t * sum_t
    if abs(denom) < 0.001:
        return 0
    slope = (n * sum_tp - sum_t * sum_p) / denom  # %/s
    # slope (%/s) → mW: rate = slope/100 * cap_mWh * 3600
    if charging:
        if slope <= 0.0005:
            return 0
    else:
        if slope >= -0.0005:
            return 0
        slope = -slope
    rate = int(slope / 100 * capacity_mwh * 3600)
    return max(0, rate)


# ─── WMI 静态电池数据缓存 ────────────────────────────────────────────

_battery_static: Optional[dict] = None


def _fetch_battery_static() -> dict:
    """通过 WMI 一次性获取设计容量、完全充电容量、电压、健康度；缓存"""
    global _battery_static
    if _battery_static is not None:
        return _battery_static

    result = {}
    try:
        import wmi
        c = wmi.WMI()
        for b in c.Win32_Battery():
            design = b.DesignCapacity or 0
            full   = b.FullChargeCapacity or 0
            volt   = b.DesignVoltage or 0
            if design > 0:
                result["design_mwh"] = design
            if full > 0:
                result["full_mwh"] = full
                result["cap_mwh"] = full
            if design > 0 and full > 0:
                result["health"] = round((full / design) * 100, 1)
            if design > 0 and volt > 0:
                result["capacity_mah"] = int(design * 1000 / volt)
            break
    except Exception:
        pass

    if result:
        _battery_static = result
    return result


def _get_health() -> Optional[float]:
    s = _fetch_battery_static()
    return s.get("health")


def _get_capacity_mah() -> Optional[int]:
    s = _fetch_battery_static()
    return s.get("capacity_mah")


def _call_system_battery_state() -> Optional[SYSTEM_BATTERY_STATE]:
    """调用 CallNtPowerInformation(SystemBatteryState) 获取实时电池状态"""
    try:
        powrprof = ctypes.windll.powrprof
        buf_size = ctypes.sizeof(SYSTEM_BATTERY_STATE)
        buf = ctypes.create_string_buffer(buf_size)
        ret = powrprof.CallNtPowerInformation(5, None, 0, buf, buf_size)
        if ret == 0:  # STATUS_SUCCESS
            s = SYSTEM_BATTERY_STATE.from_buffer_copy(buf)
            # 结构体大小校验：Rate 应在 offset 16 处读到一个合理值或 0
            # 如果读到不合理值，说明结构体对齐与本机不一致
            return s
    except Exception:
        pass
    return None


# ─── 主接口 ─────────────────────────────────────────────────────────

def get_battery_info() -> Optional[BatteryInfo]:
    """获取全面的电池信息，失败返回 None"""
    # 1. psutil 基础信息
    batt = psutil.sensors_battery()
    if batt is None:
        return None

    percent = round(batt.percent, 1)
    plugged = bool(batt.power_plugged)

    raw = batt.secsleft
    if raw < 0 or raw > 86400:   # 负值=哨兵, 超大=DWORD溢出/0xFFFFFFFF
        secsleft = None
    else:
        secsleft = raw

    # 2. Windows API 获取充放电状态 / 功率 / 预估时间
    state  = _call_system_battery_state()
    if state:
        charging    = bool(state.Charging)
        discharging = bool(state.Discharging)
        power_rate  = state.Rate
        # ── 功率合法性校验 ──
        # Rate 来自无符号 DWORD 被解释为 c_long；某些驱动会返回垃圾值
        if abs(power_rate) > 200000 or power_rate in (-2147483648, 2147483647):
            power_rate = 0
        # < 0.5W 视为无意义（残余电流 / 驱动噪声）
        if 0 < abs(power_rate) < 500:
            power_rate = 0

        # ── Rate=0 时采样重试（最多 3 次，第一次非零非噪声即可） ──
        if power_rate == 0 and charging and percent < 100:
            for _ in range(3):
                s2 = _call_system_battery_state()
                if not s2: break
                r2 = s2.Rate
                if abs(r2) >= 500 and not (abs(r2) > 200000 or r2 in (-2147483648, 2147483647)):
                    power_rate = r2
                    break
        # 修正：没插电却显示未放电 → 强制设为放电
        if not plugged and not discharging:
            discharging = True
            charging = False
    else:
        # 没有 API 数据时用 psutil 推断
        charging    = plugged and percent < 100
        discharging = not plugged
        power_rate  = 0

    # ── 从历史变化率估算功率（API 回退为 0 时的终极方案） ──
    if power_rate == 0 and (charging or discharging) and percent < 100:
        cap_mwh = state.MaxCapacity if state else 0
        if cap_mwh < 1000:  # MaxCapacity 不可信时取 WMI 数据
            cap_mwh = _fetch_battery_static().get("cap_mwh", 50000)
        r = _estimate_rate_from_history(charging, max(cap_mwh, 50000))
        if r >= 500:
            power_rate = r

    # 2.5 用 EstimatedTime 作为 secsleft 的补充（上限 24h）
    if secsleft is None and state and 0 < state.EstimatedTime < 86400:
        secsleft = state.EstimatedTime

    # 2.6 自力计算时间（容量差 × 3600 / 功率，功率需 ≥0.2W 才可信）
    if secsleft is None and state and abs(power_rate) >= 200:
        max_cap = state.MaxCapacity
        rem_cap = state.RemainingCapacity
        if charging and max_cap > rem_cap and rem_cap > 0 and max_cap > 0:
            secsleft = int((max_cap - rem_cap) * 3600 / power_rate)
        elif discharging and rem_cap > 0:
            secsleft = int(rem_cap * 3600 / abs(power_rate))

    # 2.7 历史变化率估算（终极回退 — 不依赖硬件接口）
    if secsleft is None:
        secsleft = _estimate_time_from_history(percent, charging)

    # 3. 缓存中读取静态数据
    health = _get_health()
    capacity_mah = _get_capacity_mah()
    # 回退：WMI 无电压时用 MaxCapacity 按 11.1V 典型值估算 mAh
    if capacity_mah is None and state and state.MaxCapacity > 0:
        capacity_mah = int(state.MaxCapacity * 1000 / 11100)
    # 容量 mWh
    static = _fetch_battery_static()
    capacity_mwh = static.get("cap_mwh") or (state and state.MaxCapacity) or None

    return BatteryInfo(
        percent=percent,
        plugged=plugged,
        charging=charging,
        discharging=discharging,
        power_rate=power_rate,
        secsleft=secsleft,
        health=health,
        capacity_mah=capacity_mah,
        capacity_mwh=capacity_mwh,
    )


# ─── 格式化工具 ─────────────────────────────────────────────────────

def format_time(seconds: Optional[int]) -> str:
    """秒 → X时X分 格式"""
    if seconds is None or seconds <= 0:
        return "--"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0:
        return f"{h}时{m}分"
    return f"{m}分"


def format_power(milliwatts: int) -> str:
    """mW → X.XW 格式"""
    if milliwatts is None or milliwatts <= 0:
        return ""
    return f"{milliwatts / 1000:.1f}W"
