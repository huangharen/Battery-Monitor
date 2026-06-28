"""
Overlay Window v5 · 高级液态玻璃 · 粒子 · 底部电量条 · 拖拽弹簧触感
"""

import ctypes, math, random, sys, os, winsound
from pathlib import Path
from PyQt6.QtWidgets import QWidget, QApplication, QMenu, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton, QCheckBox, QButtonGroup, QSlider
from PyQt6.QtCore import Qt, QTimer, QRect, QRectF, QPointF, QPoint, QEasingCurve
from PyQt6.QtGui import (
    QPainter, QColor, QFont, QFontDatabase, QPen, QBrush, QLinearGradient, QRadialGradient, QConicalGradient,
)

from battery_monitor import get_battery_info, BatteryInfo, format_time, format_power
import settings
import subprocess, re
_NW = subprocess.CREATE_NO_WINDOW

# ── 电源计划 ───────────────────────────────────────────────────────────
_POWER_PLANS = {
    "best_efficiency": {"guid": "a1841308-3541-4fab-bc81-f71556f20b4a", "label": "最佳能效"},
    "balanced":        {"guid": "381b4222-f694-41f0-9685-ff5bb260df2e", "label": "平衡"},
    "best_performance":{"guid": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", "label": "最佳性能"},
}


_pp_cache = None  # 电源计划缓存


def _get_current_power_plan_key():
    """返回当前电源计划 key；缓存结果避免每次 subprocess 阻塞"""
    global _pp_cache
    if _pp_cache is not None:
        return _pp_cache
    try:
        r = subprocess.run("powercfg /GetActiveScheme", capture_output=True, text=True, timeout=5, creationflags=_NW)
        m = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
                      r.stdout, re.I)
        if m:
            guid = m.group(1).lower()
            for k, v in _POWER_PLANS.items():
                if v["guid"].lower() == guid:
                    _pp_cache = k
                    return k
    except Exception:
        pass
    return None


def _set_power_plan(key: str):
    """切换电源计划（异步，不阻塞）"""
    global _pp_cache
    plan = _POWER_PLANS.get(key)
    if plan:
        try:
            subprocess.Popen(
                ['powercfg', '/S', plan['guid']],
                creationflags=_NW)
            _pp_cache = key
        except Exception:
            pass

# ── 资源目录（兼容源码运行 / PyInstaller 打包） ────────────────────────
if getattr(sys, 'frozen', False):
    _RES_DIR = Path(getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)))
else:
    _RES_DIR = Path(__file__).parent

_FONT_FAMILY = "Segoe UI"   # 默认，QApplication 创建后由 init_font() 覆盖


def init_font():
    """加载鸿蒙字体（必须在 QApplication 之后调用）"""
    global _FONT_FAMILY
    fid = QFontDatabase.addApplicationFont(str(_RES_DIR / "HarmonyOS_Sans_SC_Bold.ttf"))
    if fid >= 0:
        families = QFontDatabase.applicationFontFamilies(fid)
        if families:
            _FONT_FAMILY = families[0]
            from PyQt6.QtWidgets import QApplication
            QApplication.instance().setFont(QFont(_FONT_FAMILY, 9))

# ── 尺寸 ──────────────────────────────────────────────────────────
W, H = 174, 76
CX, CY, CR = 35, 36, 16     # 环形
PW = 3
TEXT_X = 64
R = 12

# ══════════════════════════════════════════════════════════════════
#  粒子系统
# ══════════════════════════════════════════════════════════════════
class Particle:
    __slots__ = ("x","y","vx","vy","r","alpha","phase","speed")
    def __init__(self):
        self.reset()

    def reset(self):
        self.x = random.random() * W
        self.y = random.random() * H
        self.vx = (random.random() - 0.5) * 0.25
        self.vy = (random.random() - 0.5) * 0.25
        self.r = random.random() * 1.6 + 0.4
        self.alpha = random.random() * 35 + 12
        self.phase = random.random() * math.pi * 2
        self.speed = random.random() * 0.03 + 0.01

    def update(self, dt=1):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.phase += self.speed * dt
        self.alpha = 12 + math.sin(self.phase) * 10
        if self.x < -6 or self.x > W+6 or self.y < -6 or self.y > H+6:
            self.reset()

# ══════════════════════════════════════════════════════════════════
#  颜色工具
# ══════════════════════════════════════════════════════════════════
def arc_color(pct, charging, dark=True):
    if charging:
        return QColor(0, 205, 255) if dark else QColor(45, 200, 110)
    if pct > 60:
        return QColor(60, 210, 95) if dark else QColor(50, 195, 85)
    if pct > 20:
        return QColor(245, 200, 45) if dark else QColor(160, 185, 40)
    return QColor(240, 75, 75) if dark else QColor(200, 90, 55)


# ══════════════════════════════════════════════════════════════════
#  液态玻璃层
# ══════════════════════════════════════════════════════════════════
def _glass_body(p, w, h, dark):
    g = QLinearGradient(0, 0, 0, h)
    if dark:
        g.setColorAt(0,   QColor(40, 42, 60, 212))
        g.setColorAt(0.35, QColor(24, 26, 42, 198))
        g.setColorAt(0.7,  QColor(18, 20, 34, 208))
        g.setColorAt(1,    QColor(12, 13, 24, 222))
    else:
        g.setColorAt(0,   QColor(228, 232, 244, 248))
        g.setColorAt(0.35, QColor(218, 222, 236, 240))
        g.setColorAt(0.7,  QColor(210, 215, 228, 242))
        g.setColorAt(1,    QColor(202, 207, 222, 248))
    p.fillRect(QRect(0, 0, w, h), g)


def _glass_drop_shadow(p, w, h, dark):
    g = QLinearGradient(0, h-4, 0, h)
    g.setColorAt(0, QColor(0,0,0,0))
    g.setColorAt(1, QColor(0,0,0,40 if dark else 15))
    p.fillRect(QRect(8, h-4, w-16, 4), g)


def _glass_chromatic(p, w, h):
    gl = QLinearGradient(0,0,2,0)
    gl.setColorAt(0, QColor(130,110,255,40)); gl.setColorAt(1, QColor(130,110,255,0))
    p.fillRect(QRect(0,10,2,h-20), gl)
    gr = QLinearGradient(w-3,0,w,0)
    gr.setColorAt(0, QColor(255,130,180,0)); gr.setColorAt(1, QColor(255,130,180,30))
    p.fillRect(QRect(w-3,10,3,h-20), gr)


def _glass_caustics(p, w, h, phase, dark):
    for bx, by, br, spd, off in [
        (w*.28, h*.28, 28, .7, 0), (w*.62, h*.55, 32, .5, 1.4), (w*.45, h*.72, 22, .9, 2.8)
    ]:
        a = phase * spd + off; cx = bx + math.cos(a)*20; cy = by + math.sin(a)*7
        g = QRadialGradient(QPointF(cx,cy), br)
        if dark: g.setColorAt(0, QColor(140,150,240,6)); g.setColorAt(1, QColor(140,150,240,0))
        else:    g.setColorAt(0, QColor(80,130,200,7));  g.setColorAt(1, QColor(80,130,200,0))
        p.fillRect(QRect(0,0,w,h), g)


def _glass_highlight(p, w, dark):
    g = QLinearGradient(0,0,w,0)
    if dark:
        g.setColorAt(0,  QColor(255,255,255,0))
        g.setColorAt(.12, QColor(255,255,255,60))
        g.setColorAt(.45, QColor(255,255,255,100))
        g.setColorAt(.8,  QColor(255,255,255,50))
        g.setColorAt(1,   QColor(255,255,255,0))
    else:
        g.setColorAt(0,  QColor(255,255,255,0))
        g.setColorAt(.15, QColor(255,255,255,130))
        g.setColorAt(.5,  QColor(255,255,255,210))
        g.setColorAt(.85, QColor(255,255,255,110))
        g.setColorAt(1,   QColor(255,255,255,0))
    p.fillRect(QRect(14,0,w-28,1), g)

    g2 = QLinearGradient(0,0,w,0)
    g2.setColorAt(0, QColor(255,255,255,0))
    g2.setColorAt(.35, QColor(255,255,255,18))
    g2.setColorAt(.65, QColor(255,255,255,28))
    g2.setColorAt(1,   QColor(255,255,255,0))
    p.fillRect(QRect(22,1,w-44,1), g2)


def _breathing_edge(p, w, h, phase, charging, pct, dark):
    """充电时卡片边缘呼吸光晕"""
    if not charging: return
    b = 12 + math.sin(phase * 1.8) * 8
    a = 20 + math.sin(phase * 1.8) * 12
    c = QColor(0, 200, 255, int(a))
    pen = QPen(c, 1.5)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(2, 2, w-4, h-4, R, R)

    # 底部更亮
    g = QLinearGradient(0, h-10, 0, h)
    g.setColorAt(0, QColor(0, 200, 255, 0))
    g.setColorAt(0.5, QColor(0, 200, 255, int(12 + math.sin(phase*1.8)*8)))
    g.setColorAt(1, QColor(0, 200, 255, 0))
    p.setBrush(g)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(10, h-10, w-20, 10, R, R)


def _glass_specular(p, w, h, dark, gx=.28, gy=.22):
    cx, cy, r = w*gx, h*gy, max(w,h)*.72
    g = QRadialGradient(QPointF(cx,cy), r)
    if dark:
        g.setColorAt(0,    QColor(255,255,255,25))
        g.setColorAt(.25,  QColor(255,255,255,12))
        g.setColorAt(.5,   QColor(255,255,255,3))
        g.setColorAt(1,    QColor(255,255,255,0))
    else:
        g.setColorAt(0,    QColor(255,255,255,48))
        g.setColorAt(.3,   QColor(255,255,255,20))
        g.setColorAt(1,    QColor(255,255,255,0))
    p.fillRect(QRect(0,0,w,h), g)


# ══════════════════════════════════════════════════════════════════
#  设置对话框
# ══════════════════════════════════════════════════════════════════
class SettingsDialog(QDialog):
    def __init__(self, parent, overlay):
        super().__init__(parent)
        self._overlay = overlay
        self._old_opacity = overlay.windowOpacity()
        self.setWindowTitle("设置 · 电池助手")
        self.setFixedSize(310, 380)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self.setStyleSheet("""
            QDialog { background:#181926; color:#d0d4e0; }
            QLabel  { font-size:12px; }
            QRadioButton { font-size:11px; color:#c0c5d5; spacing:6px; }
            QRadioButton::indicator { width:14px; height:14px; }
            QSlider::groove:horizontal { height:4px; background:#2a2c40; border-radius:2px; }
            QSlider::handle:horizontal { width:14px; height:14px; margin:-5px 0; background:#5c6af0; border-radius:7px; }
            QSlider::sub-page:horizontal { background:#5c6af0; border-radius:2px; }
            QPushButton { padding:4px 16px; border-radius:4px; background:#2e3050; color:#d0d4e0; border:none; }
            QPushButton:hover { background:#3e4070; }
        """)

        lay = QVBoxLayout(self); lay.setSpacing(6)

        # 主题
        lay.addWidget(QLabel("主题模式"))
        self._rb_sys = QRadioButton("跟随系统")
        self._rb_dk  = QRadioButton("深色")
        self._rb_lt  = QRadioButton("浅色")
        bg = QButtonGroup(self)
        bg.addButton(self._rb_sys); bg.addButton(self._rb_dk); bg.addButton(self._rb_lt)
        lay.addWidget(self._rb_sys); lay.addWidget(self._rb_dk); lay.addWidget(self._rb_lt)

        # 鼠标穿透 — 双按钮
        self._ct_on, self._ct_off = self._make_switch_row(lay, "鼠标穿透")
        self._ct_on.clicked.connect(lambda: self._set_ct(True))
        self._ct_off.clicked.connect(lambda: self._set_ct(False))

        # 允许拖动 — 双按钮
        self._dr_on, self._dr_off = self._make_switch_row(lay, "允许拖动")
        self._dr_on.clicked.connect(lambda: self._set_dr(True))
        self._dr_off.clicked.connect(lambda: self._set_dr(False))

        # 开机自启 — 双按钮
        self._as_on, self._as_off = self._make_switch_row(lay, "开机自启")
        self._as_on.clicked.connect(lambda: self._set_as(True))
        self._as_off.clicked.connect(lambda: self._set_as(False))

        # 强制置顶 — 双按钮
        self._ot_on, self._ot_off = self._make_switch_row(lay, "强制置顶")
        self._ot_on.clicked.connect(lambda: self._set_ot(True))
        self._ot_off.clicked.connect(lambda: self._set_ot(False))

        # 电源配置（三按钮选一）
        lay.addWidget(QLabel("电源配置选项"))
        pp = QHBoxLayout()
        self._pp_btns = {}
        pp_bg = QButtonGroup(self)
        for key in ("best_efficiency", "balanced", "best_performance"):
            plan = _POWER_PLANS[key]
            btn = QPushButton(plan["label"])
            btn.setCheckable(True); btn.setFixedWidth(84)
            pp_bg.addButton(btn)
            pp.addWidget(btn)
            self._pp_btns[key] = btn
        pp_bg.buttonClicked.connect(self._on_pp_btn)
        lay.addLayout(pp)

        # 不透明度（实时预览） — 放在最下面
        lay.addWidget(QLabel("不透明度"))
        self._op_slider = QSlider(Qt.Orientation.Horizontal)
        self._op_slider.setRange(30, 100); self._op_slider.setValue(100)
        self._op_label = QLabel("100%")
        self._op_slider.valueChanged.connect(self._on_opacity_changed)
        r = QHBoxLayout(); r.addWidget(self._op_slider); r.addWidget(self._op_label)
        lay.addLayout(r)

        lay.addStretch()

        btns = QHBoxLayout()
        reset = QPushButton("重置位置")
        reset.clicked.connect(self._reset_pos)
        sv = QPushButton("确定")
        sv.clicked.connect(self._save)
        btns.addWidget(reset); btns.addStretch(); btns.addWidget(sv)
        lay.addLayout(btns)
        self._load()

    def _make_switch_row(self, lay, label_text):
        """创建开/关双按钮（不用 checkable，手动管理状态避免双选）"""
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setFixedWidth(72)
        on_btn = QPushButton("开")
        on_btn.setFixedWidth(50)
        off_btn = QPushButton("关")
        off_btn.setFixedWidth(50)
        row.addWidget(lbl); row.addWidget(on_btn); row.addWidget(off_btn)
        row.addStretch()
        lay.addLayout(row)
        return on_btn, off_btn

    def _highlight_btn(self, btn_on, btn_off, active_on):
        """激活按钮高亮样式（btn_off 可为 None）"""
        ac = "background:#5c6af0; color:#fff; font-weight:bold; border-radius:4px;"
        ina = "background:#2e3050; color:#888; border-radius:4px;"
        if active_on:
            btn_on.setStyleSheet(ac)
            if btn_off: btn_off.setStyleSheet(ina)
        else:
            btn_on.setStyleSheet(ina)
            if btn_off: btn_off.setStyleSheet(ac)

    def _set_ct(self, on):
        """鼠标穿透开 → 允许拖动自动关"""
        self._ct_state = on
        self._highlight_btn(self._ct_on, self._ct_off, on)
        if on:
            self._dr_state = False
            self._highlight_btn(self._dr_on, self._dr_off, False)

    def _set_dr(self, on):
        """允许拖动开 → 鼠标穿透自动关"""
        self._dr_state = on
        self._highlight_btn(self._dr_on, self._dr_off, on)
        if on and self._ct_state:
            self._ct_state = False
            self._highlight_btn(self._ct_on, self._ct_off, False)

    def _set_as(self, on):
        self._as_state = on
        self._highlight_btn(self._as_on, self._as_off, on)

    def _set_ot(self, on):
        self._ot_state = on
        self._highlight_btn(self._ot_on, self._ot_off, on)
        self._overlay._apply_ontop(on)

    def _on_pp_btn(self, btn):
        for k, b in self._pp_btns.items():
            if b is btn:
                _set_power_plan(k)
                self._highlight_btn(b, None, True)
            else:
                b.setStyleSheet("background:#2e3050; color:#888; border-radius:4px;")

    def _on_opacity_changed(self, v):
        self._op_label.setText(f"{v}%")
        op = max(0.3, v / 100)
        self._overlay.setWindowOpacity(op)
        self.setWindowOpacity(op)

    def _load(self):
        t = settings.get("theme")
        {"system":self._rb_sys,"dark":self._rb_dk,"light":self._rb_lt}[t].setChecked(True)
        ct = settings.get("click_through")
        self._ct_state = ct
        self._highlight_btn(self._ct_on, self._ct_off, ct)
        dr = settings.get("draggable")
        self._dr_state = dr
        self._highlight_btn(self._dr_on, self._dr_off, dr)
        if ct:
            self._highlight_btn(self._dr_on, self._dr_off, False)
        as_ = settings.get("autostart")
        self._as_state = as_
        self._highlight_btn(self._as_on, self._as_off, as_)
        ot = settings.get("ontop")
        self._ot_state = ot
        self._highlight_btn(self._ot_on, self._ot_off, ot)
        cur_pp = _get_current_power_plan_key()
        if cur_pp and cur_pp in self._pp_btns:
            self._highlight_btn(self._pp_btns[cur_pp], None, True)
        self._op_slider.setValue(int((settings.get("opacity") or 1)*100))

    def _save(self):
        if self._rb_sys.isChecked(): t="system"
        elif self._rb_dk.isChecked(): t="dark"
        else: t="light"
        settings.set_("theme", t)
        settings.set_("click_through", self._ct_state)
        settings.set_("draggable", self._dr_state)
        settings.set_("opacity", self._op_slider.value() / 100)
        settings.set_("autostart", self._as_state)
        settings.set_autostart(self._as_state)
        settings.set_("ontop", self._ot_state)
        self._overlay._apply_settings()
        self.accept()

    def _reset_pos(self):
        settings.set_("x", None); settings.set_("y", None)
        s = QApplication.primaryScreen().availableGeometry()
        self._overlay.move(s.width() - W - 20, s.height() - H - 20)

    def reject(self):
        # 取消时恢复原有透明度
        self._overlay.setWindowOpacity(max(0.3, self._old_opacity))
        super().reject()


# ══════════════════════════════════════════════════════════════════
#  主悬浮窗
# ══════════════════════════════════════════════════════════════════
class BatteryOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self._info: BatteryInfo | None = None
        self._acrylic_ok = False
        self._disp = 0.0; self._tgt = 0.0; self._tick_elapsed = 0
        self._caustic_phase = 0.0; self._shimmer_phase = 0.0
        self._is_dark = True
        self._drag_start: QPoint | None = None
        self._spec_gx, self._spec_gy = .28, .22  # 镜面反射位置(跟随鼠标)
        self._spec_tgx, self._spec_tgy = .28, .22
        self._prev_charging = None   # 追踪充/放电状态切换
        self._transitioning = False  # 过渡动画中

        # 粒子
        self._particles = [Particle() for _ in range(10)]

        # 充电能量点
        self._energy_dots = [{"pos":random.random(),"spd":random.random()*.002+.001} for _ in range(4)]

        # winsound 预读 WAV 到内存（播放延迟 &lt;1ms）
        self._alert_data = None
        try:
            with open(str(_RES_DIR / "charge.wav"), "rb") as f:
                self._alert_data = f.read()
        except Exception:
            pass

        self._setup_window()
        self._apply_acrylic()
        self._apply_settings()
        self._setup_timer()

    # ── 窗口 ─────────────────────────────────────────────────────
    def _setup_window(self):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        if settings.get("ontop"):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setWindowTitle("Battery Monitor · 液态玻璃")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(W, H)
        sx, sy = settings.get("x"), settings.get("y")
        if sx is not None and sy is not None:
            self.move(sx, sy)
        else:
            s = QApplication.primaryScreen().availableGeometry()
            self.move(s.width()-W-20, s.height()-H-20)

    def _apply_acrylic(self):
        try:
            hwnd = int(self.winId())
            dwm = ctypes.windll.dwmapi
            v = ctypes.c_int(2)
            dwm.DwmSetWindowAttribute(hwnd,38,ctypes.byref(v),ctypes.sizeof(v))
            d = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(hwnd,20,ctypes.byref(d),ctypes.sizeof(d))
            # Win11 原生圆角
            corner = ctypes.c_int(2)  # DWMWCP_ROUND
            dwm.DwmSetWindowAttribute(hwnd,33,ctypes.byref(corner),ctypes.sizeof(corner))
            self._acrylic_ok = True
        except: self._acrylic_ok = False

    def _apply_ontop(self, ontop: bool):
        """动态切换强制置顶"""
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus
        if ontop:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.show()

    def _apply_settings(self):
        ct = settings.get("click_through")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, ct)
        t = settings.get("theme")
        self._is_dark = settings.detect_system_theme()=="dark" if t=="system" else t=="dark"
        self.setWindowOpacity(max(0.3, min(1.0, settings.get("opacity") or 1)))
        self.update()

    def _open_settings(self):
        SettingsDialog(self, self).exec()

    def _toggle_ct(self):
        v = not settings.get("click_through")
        settings.set_("click_through", v)
        if v:
            settings.set_("draggable", False)
        self._apply_settings()

    def _toggle_drag(self):
        v = not settings.get("draggable")
        settings.set_("draggable", v); self._apply_settings()

    def _set_theme(self, t):
        settings.set_("theme", t); self._apply_settings()

    # ── 定时器 ───────────────────────────────────────────────────
    def _setup_timer(self):
        self._fetch()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # 30fps, 降低 CPU 占用

    def _tick(self):
        try:
            self._tick_elapsed += 33
            if self._tick_elapsed >= 500:
                self._tick_elapsed = 0
                self._fetch()
                if settings.get("theme") == "system":
                    nd = settings.detect_system_theme() == "dark"
                    if nd != self._is_dark:
                        self._is_dark = nd

            # 百分比平滑（适配 30fps）
            d = self._tgt - self._disp
            if self._transitioning:
                if abs(d) > 0.2:
                    self._disp += d * 0.12
                else:
                    self._disp = self._tgt
                    self._transitioning = False
            elif abs(d) > 0.08:
                self._disp += d * 0.36
            else:
                self._disp = self._tgt

            # 相位
            self._caustic_phase += .008
            self._shimmer_phase += .012
            if self._caustic_phase > 100:
                self._caustic_phase -= math.pi * 30

            # 粒子
            for p in self._particles:
                p.update()

            # 镜面反射
            self._spec_gx += (self._spec_tgx - self._spec_gx) * .08
            self._spec_gy += (self._spec_tgy - self._spec_gy) * .08

            self.update()
        except Exception:
            pass

    def _fetch(self):
        try:
            new = get_battery_info()
            if new is None: return
            o = self._tgt; self._info = new; self._tgt = new.percent

            # 充/放电状态切换 → 触发过渡动画 + 提示音
            pc = self._prev_charging
            if pc is not None and new.charging != pc:
                self._disp = 0
                self._transitioning = True
                if new.charging:
                    self._play_charge_sound()
            self._prev_charging = new.charging

            if o == 0 and self._disp == 0 and not self._transitioning:
                self._disp = new.percent
            elif abs(new.percent - o) > 1 and not self._transitioning:
                self._disp = o
        except Exception:
            pass

    def _play_charge_sound(self):
        """winsound 内存播放（优先），失败回退文件路径"""
        try:
            if self._alert_data:
                winsound.PlaySound(self._alert_data,
                                   winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                return
        except Exception:
            pass
        # 回退：直接播放文件
        try:
            wav = str(_RES_DIR / "charge.wav")
            if os.path.isfile(wav):
                winsound.PlaySound(wav, winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception:
            pass

    def _restart(self):
        """重启程序"""
        exe = sys.executable
        if getattr(sys, 'frozen', False):
            os.startfile(exe)
        else:
            os.system(f'start "" "{sys.executable}" "{Path(__file__).resolve()}"')
        QApplication.instance().quit()

    # ── 鼠标 ─────────────────────────────────────────────────────
    SNAP = 18  # 磁吸阈值 (px)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and settings.get("draggable"):
            self._drag_start = e.globalPosition().toPoint()
            r = self.rect()
            self._spec_tgx = (e.position().x()/r.width()) if r.width()>0 else .28
            self._spec_tgy = (e.position().y()/r.height()) if r.height()>0 else .22
            # 🎯 拖拽暂停动画定时器，释放 CPU 让移动更流畅
            self._timer.stop()

    def mouseMoveEvent(self, e):
        if self._drag_start is not None:
            delta = e.globalPosition().toPoint() - self._drag_start
            self.move(self.pos() + delta)
            self._drag_start = e.globalPosition().toPoint()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_start = None
            self._apply_snap()
            settings.set_("x", self.x()); settings.set_("y", self.y())
            self._spec_tgx, self._spec_tgy = .28, .22
            # 🎯 恢复动画 + 立即刷新
            self._fetch()
            self._timer.start(33)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            s = QApplication.primaryScreen().availableGeometry()
            self.move(s.width() - W - 20, s.height() - H - 20)
            settings.set_("x", self.x()); settings.set_("y", self.y())

    def _apply_snap(self):
        """磁吸边缘 + 超边界回弹（上下左右一致）"""
        s = QApplication.primaryScreen().availableGeometry()
        x, y = self.x(), self.y()
        snap = self.SNAP

        # 超界回弹 + 磁吸到边缘（上下左右统一）
        if x < snap:
            x = 0
        elif x + W > s.width() - snap:
            x = s.width() - W

        if y < snap:
            y = 0
        elif y + H > s.height() - snap:
            y = s.height() - H

        self.move(x, y)

    def contextMenuEvent(self, e):
        if settings.get("click_through"): return
        menu = QMenu(self)
        menu.setStyleSheet("QMenu{background:#1c1d2a;color:#c8cdd8;border:1px solid #333;padding:4px}"
            "QMenu::item{padding:5px 20px}QMenu::item:selected{background:#2e3060}"
            "QMenu::separator{height:1px;background:#333;margin:4px 8px}")

        for text, slot, chk in [
            ("鼠标穿透", self._toggle_ct, settings.get("click_through")),
            ("允许拖动", self._toggle_drag, settings.get("draggable")),
        ]:
            a = menu.addAction(text); a.setCheckable(True); a.setChecked(chk)
            a.triggered.connect(slot)

        menu.addSeparator()
        tm = menu.addMenu("主题")
        for lb,v in [("跟随系统","system"),("深色","dark"),("浅色","light")]:
            a = tm.addAction(lb)
            a.setCheckable(True); a.setChecked(settings.get("theme")==v)
            a.triggered.connect(lambda chk,val=v: self._set_theme(val))

        menu.addSeparator()
        menu.addAction("设置...", self._open_settings)
        menu.addAction("重启", self._restart)
        menu.addAction("退出", QApplication.instance().quit)
        menu.exec(e.globalPos())

    def moveEvent(self, e):
        super().moveEvent(e)

    # ═════════════════════════════════════════════════════════════
    #  绘制主入口
    # ═════════════════════════════════════════════════════════════
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        dk = self._is_dark

        if not self._acrylic_ok:
            p.fillRect(self.rect(), QColor(14,15,26,220) if dk else QColor(230,233,242,220))

        # 玻璃层
        _glass_body(p, W, H, dk)
        _glass_drop_shadow(p, W, H, dk)
        _glass_chromatic(p, W, H)
        _glass_caustics(p, W, H, self._caustic_phase, dk)

        info = self._info
        if info:
            self._draw_arc_glow(p, self._disp, info.charging, dk)
            self._draw_energy(p, self._disp, info.charging, dk)
            self._draw_ring(p, self._disp, info.charging, dk)
            self._draw_bottom_bar(p, W, H, self._disp, info.charging, dk)
            self._draw_text(p, info, dk)
        else:
            p.setPen(QColor(150,158,175) if dk else QColor(100,105,120))
            p.setFont(QFont(_FONT_FAMILY,9))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "无电池")

        # 充电呼吸边缘光晕
        _breathing_edge(p, W, H, self._caustic_phase, info.charging if info else False,
                        self._disp, dk)

        # 粒子 → 所有内容之上，模拟浮尘
        self._draw_particles(p, dk, self._disp, info.charging if info else False)

        # 玻璃表层（高光+镜面反射 → 最后绘制以模拟玻璃外层）
        _glass_highlight(p, W, dk)
        _glass_specular(p, W, H, dk, self._spec_gx, self._spec_gy)

    # ── 环形（锥形渐变进度 + 加粗轨道） ──────────────────────────
    def _draw_ring(self, p, pct, charging, dark):
        # 轨道 — 粗一圈 + 微光
        trk = QColor(60,65,80,140) if dark else QColor(175,180,192,140)
        p.setPen(QPen(trk, PW+2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(CX-CR-1, CY-CR-1, CR*2+2, CR*2+2, 1440, 360*16)

        # 内轨 — 细
        trk2 = QColor(80,85,100,90) if dark else QColor(190,195,205,90)
        p.setPen(QPen(trk2, PW, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(CX-CR, CY-CR, CR*2, CR*2, 1440, 360*16)

        c = arc_color(pct, charging, dark)
        span = int(-360*16*max(0,min(pct,100))/100)
        if span != 0:
            # 锥形渐变 — 沿弧从起点到终点颜色自然过渡
            seg = pct / 100
            cg = QConicalGradient(QPointF(CX, CY), 90)
            cg.setColorAt(0,        c)
            cg.setColorAt(seg * 0.4, c.lighter(135))
            cg.setColorAt(seg,       c.lighter(110))
            # 超出弧范围 → 透明（让轨道透出）
            cg.setColorAt(min(seg + 0.03, 1), QColor(c.red(), c.green(), c.blue(), 20))
            cg.setColorAt(1, QColor(0, 0, 0, 0))

            p.setPen(QPen(QBrush(cg), PW, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(CX-CR, CY-CR, CR*2, CR*2, 1440, span)

            # 前导光点
            ea = math.radians((1440 + span) / 16.0)
            lx = CX + CR * math.cos(ea)
            ly = CY - CR * math.sin(ea)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c.red(), c.green(), c.blue(), 220))
            p.drawEllipse(QPointF(lx, ly), 2.5, 2.5)
            p.setBrush(QColor(c.red(), c.green(), c.blue(), 60))
            p.drawEllipse(QPointF(lx, ly), 5.5, 5.5)

        f = QFont(_FONT_FAMILY, 12, QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(QColor(238,241,250) if dark else QColor(0,0,0))
        p.drawText(QRect(CX-CR, CY-CR, CR*2, CR*2),
                   Qt.AlignmentFlag.AlignCenter, f"{int(round(pct))}")

    def _draw_arc_glow(self, p, pct, charging, dark=True):
        """外层辉光 — 三层柔光"""
        c = arc_color(pct, charging, dark)
        span = int(-360*16*max(0,min(pct,100))/100)
        if span == 0: return

        glow = QColor(c.red(), c.green(), c.blue(), 45)
        p.setPen(QPen(glow, PW+7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(CX-CR-2, CY-CR-2, CR*2+4, CR*2+4, 1440, span)

        glow2 = QColor(c.red(), c.green(), c.blue(), 22)
        p.setPen(QPen(glow2, PW+13, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(CX-CR-5, CY-CR-5, CR*2+10, CR*2+10, 1440, span)

        glow3 = QColor(c.red(), c.green(), c.blue(), 8)
        p.setPen(QPen(glow3, PW+22, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(CX-CR-9, CY-CR-9, CR*2+18, CR*2+18, 1440, span)

    # ── 充电能量流动（带拖尾） ──────────────────────────────────
    def _draw_energy(self, p, pct, charging, dark=True):
        if not charging or pct>=100: return
        ec = QColor(45, 200, 110) if not dark else QColor(0, 205, 255)
        for dot in self._energy_dots:
            total = self._caustic_phase * dot["spd"] + dot["pos"]
            progress = (total % 1.0) * pct/100

            deg = -90 + progress*360
            rad2 = math.radians(deg)
            ex = CX + CR*0.75 * math.cos(rad2)
            ey = CY + CR*0.75 * math.sin(rad2)

            pulse = 60 + 60*math.sin(self._caustic_phase*3 + dot["pos"]*10)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ec.red(), ec.green(), ec.blue(), int(pulse)))
            p.drawEllipse(QPointF(ex,ey), 2.2, 2.2)

            # 拖尾：后方画2个渐小渐隐的小点
            for j in range(1, 4):
                tp = progress - j * 0.015
                if tp < 0: continue
                td = -90 + tp*360
                tr2 = math.radians(td)
                tx = CX + CR*0.75 * math.cos(tr2)
                ty = CY + CR*0.75 * math.sin(tr2)
                ta = int(pulse * (0.4 / j))
                tr = 2.2 * (0.6 / j)
                p.setBrush(QColor(ec.red(), ec.green(), ec.blue(), ta))
                p.drawEllipse(QPointF(tx, ty), tr, tr)

    # ── 底部电量条 ──────────────────────────────────────────────
    def _draw_bottom_bar(self, p, w, h, pct, charging, dark):
        bx, by = 10, h-7
        bw, bh = w-20, 3
        fill_w = int(bw * max(0,min(pct,100)) / 100)

        c = arc_color(pct, charging, dark)
        bg = QColor(55,60,75,60) if dark else QColor(160,170,190,60)

        p.setPen(Qt.PenStyle.NoPen)

        # 外发光
        if fill_w>0:
            glow = QColor(c.red(), c.green(), c.blue(), 16)
            p.setBrush(glow)
            p.drawRoundedRect(bx-1, by-1, fill_w+2, bh+4, 2.5, 2.5)

        # 轨道
        p.setBrush(bg)
        p.drawRoundedRect(bx, by, bw, bh, 1.5, 1.5)

        # 填充
        if fill_w>0:
            p.setBrush(c)
            p.drawRoundedRect(bx, by, fill_w, bh, 1.5, 1.5)

            # 扫光（shimmer）
            sx = bx + ((self._shimmer_phase*1.5) % 1.0) * bw
            sg = QLinearGradient(sx-8, 0, sx+8, 0)
            sg.setColorAt(0,   QColor(255,255,255,0))
            sg.setColorAt(0.5, QColor(255,255,255,90))
            sg.setColorAt(1,   QColor(255,255,255,0))
            p.setBrush(sg)
            p.drawRoundedRect(bx, by, fill_w, bh, 1.5, 1.5)

    # ── 粒子（颜色跟随电量） ─────────────────────────────────────
    def _draw_particles(self, p, dark, pct=50, charging=False):
        p.setPen(Qt.PenStyle.NoPen)
        # 根据电量决定粒子色调：高绿 → 中黄 → 低红
        if charging:
            rc, gc, bc = 130, 210, 255  # 充电时蓝青色
        elif pct > 60:
            rc, gc, bc = 120, 220, 140  # 绿色
        elif pct > 20:
            rc, gc, bc = 245, 200, 60   # 黄色
        else:
            rc, gc, bc = 245, 100, 90   # 红色

        for pt in self._particles:
            a = max(0, min(255, int(pt.alpha * (1 if dark else 1.2))))
            if a<=1: continue
            c = QColor(rc, gc, bc, a)
            p.setBrush(c)
            p.drawEllipse(QPointF(pt.x, pt.y), pt.r, pt.r)

    # ── 文字 ────────────────────────────────────────────────────
    def _draw_text(self, p, info, dark):
        fg  = QColor(238,241,250) if dark else QColor(0,0,0)
        fg2 = QColor(160,170,188) if dark else QColor(18,22,36)
        fg3 = QColor(100,108,125) if dark else QColor(50,55,70)

        # 状态 + 功率
        if info.plugged and info.percent >= 99.5:
            st = "已满"
        elif info.charging:
            st = "充电"
        elif info.discharging:
            st = "放电"
        else:
            st = "待机"

        l1 = st
        if info.power_rate!=0: l1 += f"  {abs(info.power_rate)/1000:.1f}W"
        f1 = QFont(_FONT_FAMILY, 10)
        p.setFont(f1); p.setPen(fg); p.drawText(TEXT_X, 22, l1)

        # 第二行：时长（醒目）
        f2 = QFont(_FONT_FAMILY, 9)
        p.setFont(f2)
        if info.secsleft is not None and info.secsleft>0:
            if info.charging:
                lbl = "充满还需"
            else:
                lbl = "还可使用"
            p.setPen(fg2)
            p.drawText(TEXT_X, 40, f"{lbl}  {format_time(info.secsleft)}")
        else:
            p.setPen(fg3); p.drawText(TEXT_X, 40, "计算中...")

        # 第三行：健康（极小）
        y3 = 53
        if info.health is not None:
            f3 = QFont(_FONT_FAMILY, 7)
            p.setFont(f3); p.setPen(fg3)
            p.drawText(TEXT_X, y3, f"健康 {info.health:.0f}%")
            y3 += 12

        # 第四行：电池容量 (mWh)
        cap = info.capacity_mwh or info.capacity_mah
        if cap is not None and cap > 0:
            p.setFont(QFont(_FONT_FAMILY, 7))
            p.setPen(fg3)
            p.drawText(TEXT_X, y3, f"容量 {cap} mWh")
