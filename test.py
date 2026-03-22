"""
Floating Countdown Timer Widget
--------------------------------
Features:
  - Always-on-top floating window, draggable
  - Multi-monitor aware: detect monitors, pick one, presets snap to that monitor
  - Position presets: top-left/mid/right, center, bottom-left/mid/right
  - Manual X/Y coordinate input
  - Resizable donut (S / M / L / XL or custom px)
  - Multiple named segments (e.g. 20m + 40m inside a 1h total)
  - Live countdown with play / pause / reset
  - Donut ring depletes as time passes; active segment highlighted
  - Collapse / expand the widget
"""

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess, sys, platform

# ─── Palette ─────────────────────────────────────────────────────────────────

SEG_COLORS = [
    "#7F77DD", "#1D9E75", "#D85A30", "#D4537E",
    "#378ADD", "#639922", "#BA7517", "#E24B4A",
    "#5DCAA5", "#97C459",
]

BG_DARK   = "#1A1A2E"
BG_PANEL  = "#16213E"
ACCENT    = "#7F77DD"
TEXT_MAIN = "#E8E8F0"
TEXT_DIM  = "#888899"
RING_BG   = "#2A2A3E"
GREEN     = "#1D9E75"
RED       = "#E24B4A"

# ─── Monitor detection ───────────────────────────────────────────────────────

def get_monitors():
    """
    Return a list of dicts: {name, x, y, w, h}
    Works on Linux (xrandr), macOS (system_profiler / Quartz), Windows (ctypes).
    Falls back to the full virtual desktop as a single monitor if detection fails.
    """
    monitors = []
    os_name = platform.system()

    try:
        if os_name == "Linux":
            out = subprocess.check_output(["xrandr", "--query"],
                                          stderr=subprocess.DEVNULL).decode()
            for line in out.splitlines():
                if " connected" in line:
                    # e.g.  eDP-1 connected primary 1920x1080+0+0
                    parts = line.split()
                    name = parts[0]
                    for part in parts:
                        if "x" in part and "+" in part:
                            try:
                                res, ox, oy = part.replace("+", "x").split("x")[0], \
                                              part.split("+")[1], part.split("+")[2]
                                wh = part.split("+")[0].split("x")
                                monitors.append({
                                    "name": name,
                                    "x": int(ox), "y": int(oy),
                                    "w": int(wh[0]), "h": int(wh[1]),
                                })
                            except Exception:
                                pass
                            break

        elif os_name == "Windows":
            import ctypes
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()

            MONITOR_DEFAULTTONEAREST = 2
            EnumDisplayMonitors = user32.EnumDisplayMonitors

            class RECT(ctypes.Structure):
                _fields_ = [("left","l_int"),("top","l_int"),
                             ("right","l_int"),("bottom","l_int")]
            # Use simpler approach via GetSystemMetrics for virtual desktop
            # and EnumDisplayMonitors callback
            monitors_found = []
            MonitorEnumProc = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_ulong, ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_long), ctypes.c_double)

            def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
                rc = lprcMonitor.contents
                # rc is actually a RECT pointer
                info = ctypes.create_string_buffer(40)
                ctypes.cast(info, ctypes.POINTER(ctypes.c_ulong))[0] = 40
                if user32.GetMonitorInfoW(hMonitor, info):
                    import struct
                    # MONITORINFO: cbSize(4) rcMonitor(16) rcWork(16) dwFlags(4)
                    data = struct.unpack("IiiiiiiiI", info.raw[:36])
                    monitors_found.append({
                        "name": f"Monitor {len(monitors_found)+1}",
                        "x": data[1], "y": data[2],
                        "w": data[3] - data[1], "h": data[4] - data[2],
                    })
                return True

            proc = MonitorEnumProc(callback)
            EnumDisplayMonitors(None, None, proc, 0)
            monitors = monitors_found

        elif os_name == "Darwin":
            try:
                from Quartz import CGDisplayBounds, CGGetActiveDisplayList
                _, ids, _ = CGGetActiveDisplayList(32, None, None)
                for i, did in enumerate(ids):
                    b = CGDisplayBounds(did)
                    monitors.append({
                        "name": f"Display {i+1}",
                        "x": int(b.origin.x), "y": int(b.origin.y),
                        "w": int(b.size.width), "h": int(b.size.height),
                    })
            except ImportError:
                pass  # fall through to fallback

    except Exception:
        pass

    return monitors if monitors else None   # None = use fallback


# ─── Helpers ─────────────────────────────────────────────────────────────────

def fmt_seconds(secs: float) -> str:
    s = int(secs)
    h, rem = divmod(s, 3600)
    m, ss  = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{ss:02d}"
    return f"{m}:{ss:02d}"

def fmt_min(minutes: float) -> str:
    m = int(round(minutes))
    if m < 60:
        return f"{m}m"
    h, r = divmod(m, 60)
    return f"{h}h {r}m" if r else f"{h}h"

def draw_donut(canvas, cx, cy, r, stroke, segments, total_sec, elapsed_sec):
    canvas.delete("donut")
    x0, y0, x1, y1 = cx - r, cy - r, cx + r, cy + r

    canvas.create_arc(x0, y0, x1, y1, start=0, extent=359.999,
                      outline=RING_BG, width=stroke, style="arc", tags="donut")

    if total_sec <= 0:
        return

    acc = 0.0
    active_idx = len(segments) - 1
    for i, seg in enumerate(segments):
        acc += seg["sec"]
        if elapsed_sec < acc:
            active_idx = i
            break

    start_deg = 90
    for i, seg in enumerate(segments):
        extent = (seg["sec"] / total_sec) * 360
        w = stroke + 4 if i == active_idx else stroke
        canvas.create_arc(x0, y0, x1, y1,
                          start=start_deg, extent=-extent,
                          outline=seg["color"], width=w,
                          style="arc", tags="donut")
        start_deg -= extent

    elapsed_extent = min(elapsed_sec / total_sec, 1.0) * 360
    if elapsed_extent > 0:
        canvas.create_arc(x0, y0, x1, y1,
                          start=90, extent=-elapsed_extent,
                          outline="#0D0D1A", width=max(stroke - 3, 2),
                          style="arc", tags="donut")


# ─── Size presets ─────────────────────────────────────────────────────────────

SIZE_PRESETS = {
    "S":  80,
    "M":  130,
    "L":  180,
    "XL": 240,
}


# ─── Settings / control window ────────────────────────────────────────────────

class ControlWindow(tk.Toplevel):
    def __init__(self, master, widget):
        super().__init__(master)
        self.widget = widget
        self.title("Widget Settings")
        self.resizable(False, False)
        self.configure(bg=BG_DARK)
        self.protocol("WM_DELETE_WINDOW", self.withdraw)
        self._build()
        self._refresh_seg_list()
        self._refresh_monitor_list()

    def _lbl(self, parent, text):
        return tk.Label(parent, text=text, bg=BG_DARK,
                        fg=TEXT_DIM, font=("Helvetica", 10))

    def _entry(self, parent, width=10, textvariable=None):
        kw = dict(width=width, bg=BG_PANEL, fg=TEXT_MAIN,
                  insertbackground=TEXT_MAIN, relief="flat",
                  highlightthickness=1, highlightbackground=RING_BG,
                  highlightcolor=ACCENT, font=("Helvetica", 11))
        if textvariable:
            kw["textvariable"] = textvariable
        return tk.Entry(parent, **kw)

    def _btn(self, parent, text, cmd, accent=False, danger=False):
        bg = RED if danger else (ACCENT if accent else BG_PANEL)
        fg = "#fff" if (accent or danger) else TEXT_MAIN
        return tk.Button(parent, text=text, command=cmd,
                         bg=bg, fg=fg, activebackground=ACCENT,
                         activeforeground="#fff", relief="flat",
                         padx=10, pady=4, font=("Helvetica", 10),
                         cursor="hand2")

    def _section(self, text):
        f = tk.Frame(self, bg=BG_DARK)
        f.pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(f, text=text.upper(), bg=BG_DARK,
                 fg=ACCENT, font=("Helvetica", 9, "bold")).pack(anchor="w")
        ttk.Separator(self).pack(fill="x", padx=16, pady=2)

    def _build(self):
        # ── Header ────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=ACCENT)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚙  Floating Widget Settings",
                 bg=ACCENT, fg="#fff", font=("Helvetica", 13, "bold"),
                 pady=10).pack(side="left", padx=16)

        # ── Widget label ──────────────────────────────────────────────────
        self._section("Widget label")
        r = tk.Frame(self, bg=BG_DARK); r.pack(fill="x", padx=16, pady=4)
        self._lbl(r, "Label:").pack(side="left")
        self.var_title = tk.StringVar(value=self.widget.title_var.get())
        self._entry(r, 20, self.var_title).pack(side="left", padx=6)
        self._btn(r, "Apply", self._apply_title, accent=True).pack(side="left")

        # ── Total duration ────────────────────────────────────────────────
        self._section("Total duration")
        r2 = tk.Frame(self, bg=BG_DARK); r2.pack(fill="x", padx=16, pady=4)
        self._lbl(r2, "Minutes:").pack(side="left")
        self.var_total = tk.StringVar(value=str(self.widget.total_min))
        self._entry(r2, 7, self.var_total).pack(side="left", padx=6)
        self._btn(r2, "Set", self._apply_total, accent=True).pack(side="left")

        # ── Widget size ───────────────────────────────────────────────────
        self._section("Widget size")
        sz = tk.Frame(self, bg=BG_DARK); sz.pack(fill="x", padx=16, pady=4)
        for label, val in SIZE_PRESETS.items():
            tk.Button(sz, text=label, width=4, bg=BG_PANEL, fg=TEXT_MAIN,
                      activebackground=ACCENT, activeforeground="#fff",
                      relief="flat", pady=4, cursor="hand2",
                      font=("Helvetica", 10),
                      command=lambda v=val: self.widget.set_size(v)
                      ).pack(side="left", padx=3)

        sz2 = tk.Frame(self, bg=BG_DARK); sz2.pack(fill="x", padx=16, pady=(2, 4))
        self._lbl(sz2, "Custom px:").pack(side="left")
        self.var_size = tk.StringVar(value=str(self.widget.widget_size))
        self._entry(sz2, 6, self.var_size).pack(side="left", padx=6)
        self._btn(sz2, "Apply", self._apply_custom_size, accent=True).pack(side="left")

        # ── Monitor selection ─────────────────────────────────────────────
        self._section("Monitor")
        self.monitor_frame = tk.Frame(self, bg=BG_DARK)
        self.monitor_frame.pack(fill="x", padx=16, pady=4)
        # populated later by _refresh_monitor_list()

        # ── Position presets ──────────────────────────────────────────────
        self._section("Position presets")
        grid = tk.Frame(self, bg=BG_DARK)
        grid.pack(padx=16, pady=4)
        presets = [
            ("↖ Top-left", "tl"), ("↑ Top-mid",  "tm"), ("↗ Top-right", "tr"),
            ("⊙ Center",   "c"),  None,                   None,
            ("↙ Bot-left", "bl"), ("↓ Bot-mid",  "bm"),  ("↘ Bot-right", "br"),
        ]
        for idx, item in enumerate(presets):
            ri, ci = divmod(idx, 3)
            if item is None:
                tk.Label(grid, text="", bg=BG_DARK, width=10).grid(
                    row=ri, column=ci, padx=3, pady=3)
                continue
            label, key = item
            tk.Button(grid, text=label, width=10, bg=BG_PANEL, fg=TEXT_MAIN,
                      activebackground=ACCENT, activeforeground="#fff",
                      relief="flat", pady=5, cursor="hand2",
                      font=("Helvetica", 9),
                      command=lambda k=key: self.widget.move_to_preset(k)
                      ).grid(row=ri, column=ci, padx=3, pady=3)

        # ── Manual X / Y ──────────────────────────────────────────────────
        self._section("Manual position (px, absolute screen)")
        r3 = tk.Frame(self, bg=BG_DARK); r3.pack(fill="x", padx=16, pady=4)
        self._lbl(r3, "X:").pack(side="left")
        self.var_x = tk.StringVar(value="40")
        self._entry(r3, 6, self.var_x).pack(side="left", padx=4)
        self._lbl(r3, "Y:").pack(side="left", padx=(8, 0))
        self.var_y = tk.StringVar(value="40")
        self._entry(r3, 6, self.var_y).pack(side="left", padx=4)
        self._btn(r3, "Go", self._apply_xy, accent=True).pack(side="left", padx=6)

        # ── Add segment ───────────────────────────────────────────────────
        self._section("Add segment")
        r4 = tk.Frame(self, bg=BG_DARK); r4.pack(fill="x", padx=16, pady=4)
        self._lbl(r4, "Label:").pack(side="left")
        self.var_seg_name = tk.StringVar()
        self._entry(r4, 12, self.var_seg_name).pack(side="left", padx=4)
        self._lbl(r4, "Min:").pack(side="left", padx=(8, 0))
        self.var_seg_min = tk.StringVar()
        self._entry(r4, 6, self.var_seg_min).pack(side="left", padx=4)
        self._btn(r4, "+ Add", self._add_segment, accent=True).pack(side="left", padx=6)

        # ── Segment list ──────────────────────────────────────────────────
        self._section("Segments")
        self.seg_frame = tk.Frame(self, bg=BG_DARK)
        self.seg_frame.pack(fill="x", padx=16, pady=(0, 4))

        # ── Bottom bar ────────────────────────────────────────────────────
        bot = tk.Frame(self, bg=BG_PANEL)
        bot.pack(fill="x", pady=(10, 0))
        self._btn(bot, "Close", self.withdraw).pack(side="right", padx=12, pady=8)

    # ── Monitor UI ────────────────────────────────────────────────────────

    def _refresh_monitor_list(self):
        for child in self.monitor_frame.winfo_children():
            child.destroy()

        monitors = self.widget.monitors
        if not monitors:
            tk.Label(self.monitor_frame,
                     text="Only one display detected (or detection unavailable).",
                     bg=BG_DARK, fg=TEXT_DIM, font=("Helvetica", 9),
                     wraplength=340).pack(anchor="w")
            return

        tk.Label(self.monitor_frame,
                 text="Presets and center will snap to the selected monitor:",
                 bg=BG_DARK, fg=TEXT_DIM, font=("Helvetica", 9),
                 wraplength=340).pack(anchor="w", pady=(0, 4))

        btn_row = tk.Frame(self.monitor_frame, bg=BG_DARK)
        btn_row.pack(fill="x")

        self._mon_btns = []
        for i, m in enumerate(monitors):
            label = f"{m['name']}\n{m['w']}×{m['h']}"
            b = tk.Button(btn_row, text=label, bg=BG_PANEL, fg=TEXT_MAIN,
                          activebackground=ACCENT, activeforeground="#fff",
                          relief="flat", padx=8, pady=5, cursor="hand2",
                          font=("Helvetica", 9), justify="center",
                          command=lambda idx=i: self._select_monitor(idx))
            b.pack(side="left", padx=3)
            self._mon_btns.append(b)

        self._update_monitor_buttons()

    def _select_monitor(self, idx):
        self.widget.active_monitor = idx
        self._update_monitor_buttons()

    def _update_monitor_buttons(self):
        for i, b in enumerate(self._mon_btns):
            if i == self.widget.active_monitor:
                b.config(bg=ACCENT, fg="#fff")
            else:
                b.config(bg=BG_PANEL, fg=TEXT_MAIN)

    # ── Actions ───────────────────────────────────────────────────────────

    def _apply_title(self):
        self.widget.title_var.set(self.var_title.get() or "Widget")

    def _apply_custom_size(self):
        try:
            v = int(self.var_size.get())
            assert 40 <= v <= 600
        except Exception:
            messagebox.showerror("Error", "Enter a size between 40 and 600.", parent=self)
            return
        self.widget.set_size(v)

    def _apply_total(self):
        try:
            v = int(self.var_total.get())
            assert v > 0
        except Exception:
            messagebox.showerror("Error", "Enter a positive integer.", parent=self)
            return
        used = sum(s["min"] for s in self.widget.segments)
        if used > v:
            messagebox.showwarning("Warning",
                f"Segment total ({fmt_min(used)}) exceeds new total ({fmt_min(v)}).\n"
                "Remove or shorten segments first.", parent=self)
            return
        self.widget.total_min = v
        self.widget.reset_timer()
        self._refresh_seg_list()

    def _apply_xy(self):
        try:
            x, y = int(self.var_x.get()), int(self.var_y.get())
        except Exception:
            messagebox.showerror("Error", "X and Y must be integers.", parent=self)
            return
        self.widget.geometry(f"+{x}+{y}")

    def _add_segment(self):
        name = self.var_seg_name.get().strip() or f"Segment {len(self.widget.segments)+1}"
        try:
            mins = float(self.var_seg_min.get())
            assert mins > 0
        except Exception:
            messagebox.showerror("Error", "Enter a duration > 0.", parent=self)
            return
        used = sum(s["min"] for s in self.widget.segments)
        if used + mins > self.widget.total_min:
            over = (used + mins) - self.widget.total_min
            messagebox.showwarning("Over budget",
                f"Exceeds total by {fmt_min(over)}.\n"
                "Increase the total or shorten existing segments.", parent=self)
            return
        color = SEG_COLORS[len(self.widget.segments) % len(SEG_COLORS)]
        self.widget.segments.append({"name": name, "min": mins,
                                     "sec": mins * 60, "color": color})
        self.var_seg_name.set("")
        self.var_seg_min.set("")
        self.widget.reset_timer()
        self._refresh_seg_list()

    def _refresh_seg_list(self):
        for child in self.seg_frame.winfo_children():
            child.destroy()

        segs  = self.widget.segments
        total = self.widget.total_min
        used  = sum(s["min"] for s in segs)

        bar = tk.Canvas(self.seg_frame, height=14, bg=BG_PANEL, highlightthickness=0)
        bar.pack(fill="x", pady=(0, 6))
        bar.update_idletasks()
        W = max(bar.winfo_width(), 340)
        x = 0
        for s in segs:
            w = int((s["min"] / total) * W) if total else 0
            bar.create_rectangle(x, 0, x + w, 14, fill=s["color"], outline="")
            x += w
        if used < total:
            bar.create_rectangle(x, 0, W, 14, fill=RING_BG, outline="")

        if not segs:
            tk.Label(self.seg_frame, text="No segments yet.",
                     bg=BG_DARK, fg=TEXT_DIM, font=("Helvetica", 10)).pack(anchor="w")
            return

        for i, s in enumerate(segs):
            row = tk.Frame(self.seg_frame, bg=BG_PANEL, pady=5, padx=8)
            row.pack(fill="x", pady=2)
            dot = tk.Canvas(row, width=10, height=10, bg=BG_PANEL, highlightthickness=0)
            dot.create_oval(0, 0, 10, 10, fill=s["color"], outline="")
            dot.pack(side="left", padx=(0, 6))
            tk.Label(row, text=s["name"], bg=BG_PANEL, fg=TEXT_MAIN,
                     font=("Helvetica", 10)).pack(side="left")
            tk.Label(row, text=fmt_min(s["min"]), bg=BG_PANEL, fg=TEXT_DIM,
                     font=("Helvetica", 10)).pack(side="left", padx=8)
            pct = round((s["min"] / total) * 100) if total else 0
            tk.Label(row, text=f"{pct}%", bg=BG_PANEL, fg=TEXT_DIM,
                     font=("Helvetica", 9)).pack(side="left")
            tk.Button(row, text="✕", bg=BG_PANEL, fg=RED, relief="flat",
                      cursor="hand2", font=("Helvetica", 9),
                      command=lambda j=i: self._remove_seg(j)).pack(side="right")

        rem = total - used
        if rem > 0:
            tk.Label(self.seg_frame,
                     text=f"  Remaining: {fmt_min(rem)} / {fmt_min(total)}",
                     bg=BG_DARK, fg=TEXT_DIM,
                     font=("Helvetica", 9)).pack(anchor="w", pady=(4, 0))

    def _remove_seg(self, idx):
        self.widget.segments.pop(idx)
        self.widget.reset_timer()
        self._refresh_seg_list()


# ─── Floating widget ──────────────────────────────────────────────────────────

class FloatingWidget(tk.Tk):
    def __init__(self):
        super().__init__()

        self.total_min   = 60
        self.segments    = []
        self.title_var   = tk.StringVar(value="My Timer")
        self.widget_size = SIZE_PRESETS["M"]   # canvas px

        # timer state
        self._total_sec   = self.total_min * 60
        self._elapsed_sec = 0.0
        self._running     = False
        self._after_id    = None

        self._collapsed = False
        self._drag_x = self._drag_y = 0

        # monitor state
        self.monitors      = get_monitors()   # list of dicts or None
        self.active_monitor = 0              # index into self.monitors

        self._setup_window()
        self._build_ui()

        self.control = ControlWindow(self, self)
        self._draw()
        self.after(200, self._show_control)

    # ── Window ────────────────────────────────────────────────────────────

    def _setup_window(self):
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.95)
        self.configure(bg=BG_DARK)
        self.geometry("+40+40")

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.header = tk.Frame(self, bg=BG_PANEL)
        self.header.pack(fill="x")

        self.lbl_title = tk.Label(
            self.header, textvariable=self.title_var,
            bg=BG_PANEL, fg=TEXT_MAIN,
            font=("Helvetica", 11, "bold"), pady=7, padx=10)
        self.lbl_title.pack(side="left")

        for w in (self.header, self.lbl_title):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>",     self._drag_move)

        btn_kw = dict(bg=BG_PANEL, relief="flat", cursor="hand2",
                      fg=TEXT_DIM, font=("Helvetica", 11), padx=6, pady=5)
        tk.Button(self.header, text="⚙", command=self._show_control,
                  **btn_kw).pack(side="right")
        self.btn_collapse = tk.Button(self.header, text="−",
                                      command=self._toggle_collapse, **btn_kw)
        self.btn_collapse.pack(side="right")
        tk.Button(self.header, text="✕", command=self.destroy,
                  **{**btn_kw, "fg": RED}).pack(side="right")

        self.body = tk.Frame(self, bg=BG_DARK, padx=14, pady=10)
        self.body.pack(fill="both")

        s = self.widget_size
        self.canvas = tk.Canvas(self.body, width=s, height=s,
                                bg=BG_DARK, highlightthickness=0)
        self.canvas.pack()

        ctrl = tk.Frame(self.body, bg=BG_DARK)
        ctrl.pack(pady=(6, 0))

        btn2 = dict(relief="flat", cursor="hand2",
                    font=("Helvetica", 16), padx=10, pady=2,
                    activebackground=BG_DARK)
        self.btn_play = tk.Button(ctrl, text="▶", bg=BG_DARK, fg=GREEN,
                                  activeforeground=GREEN,
                                  command=self._toggle_play, **btn2)
        self.btn_play.pack(side="left")
        tk.Button(ctrl, text="⟳", bg=BG_DARK, fg=TEXT_DIM,
                  activeforeground=TEXT_MAIN,
                  command=self.reset_timer, **btn2).pack(side="left")

        self.legend = tk.Frame(self.body, bg=BG_DARK)
        self.legend.pack(fill="x", pady=(8, 0))

    # ── Drag ──────────────────────────────────────────────────────────────

    def _drag_start(self, e):
        self._drag_x = e.x_root - self.winfo_x()
        self._drag_y = e.y_root - self.winfo_y()

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    # ── Active monitor bounds ─────────────────────────────────────────────

    def _monitor_rect(self):
        """Return (mx, my, mw, mh) for the currently selected monitor."""
        if self.monitors and 0 <= self.active_monitor < len(self.monitors):
            m = self.monitors[self.active_monitor]
            return m["x"], m["y"], m["w"], m["h"]
        # Fallback: full virtual desktop origin + screen size
        return 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()

    # ── Position presets ──────────────────────────────────────────────────

    def move_to_preset(self, key):
        self.update_idletasks()
        mx, my, mw, mh = self._monitor_rect()
        ww = self.winfo_width()
        wh = self.winfo_height()
        pad = 20

        pos = {
            "tl": (mx + pad,               my + pad),
            "tm": (mx + (mw - ww) // 2,    my + pad),
            "tr": (mx + mw - ww - pad,      my + pad),
            "c":  (mx + (mw - ww) // 2,    my + (mh - wh) // 2),
            "bl": (mx + pad,               my + mh - wh - pad),
            "bm": (mx + (mw - ww) // 2,    my + mh - wh - pad),
            "br": (mx + mw - ww - pad,      my + mh - wh - pad),
        }
        x, y = pos.get(key, (mx + pad, my + pad))
        self.geometry(f"+{x}+{y}")

    # ── Size ──────────────────────────────────────────────────────────────

    def set_size(self, px: int):
        self.widget_size = px
        self.canvas.config(width=px, height=px)
        # update custom size field in settings if open
        if hasattr(self, "control") and self.control.winfo_exists():
            self.control.var_size.set(str(px))
        self._draw()

    # ── Collapse ──────────────────────────────────────────────────────────

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self.body.pack_forget()
            self.btn_collapse.config(text="+")
        else:
            self.body.pack(fill="both")
            self.btn_collapse.config(text="−")
            self._draw()

    # ── Timer ─────────────────────────────────────────────────────────────

    def reset_timer(self):
        self._running = False
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        self._total_sec   = self.total_min * 60
        self._elapsed_sec = 0.0
        self.btn_play.config(text="▶", fg=GREEN)
        self._draw()

    def _toggle_play(self):
        if self._elapsed_sec >= self._total_sec:
            self.reset_timer()
            return
        self._running = not self._running
        if self._running:
            self.btn_play.config(text="⏸", fg=RED)
            self._tick()
        else:
            self.btn_play.config(text="▶", fg=GREEN)
            if self._after_id:
                self.after_cancel(self._after_id)
                self._after_id = None

    def _tick(self):
        if not self._running:
            return
        self._elapsed_sec += 1
        self._draw()
        if self._elapsed_sec >= self._total_sec:
            self._running = False
            self.btn_play.config(text="▶", fg=GREEN)
            self.bell()
            return
        self._after_id = self.after(1000, self._tick)

    # ── Draw ──────────────────────────────────────────────────────────────

    def _draw(self):
        if self._collapsed:
            return

        s  = self.widget_size
        cx = cy = s // 2

        # scale donut geometry with size
        r      = int(s * 0.38)
        stroke = max(int(s * 0.10), 6)
        font_s = max(int(s * 0.11), 9)

        draw_donut(self.canvas, cx, cy, r, stroke,
                   self.segments, self._total_sec, self._elapsed_sec)

        remaining = max(self._total_sec - self._elapsed_sec, 0)
        self.canvas.delete("centerlabel")
        self.canvas.create_text(cx, cy, text=fmt_seconds(remaining),
                                fill=TEXT_MAIN,
                                font=("Helvetica", font_s, "bold"),
                                tags="centerlabel")

        for child in self.legend.winfo_children():
            child.destroy()

        acc = 0.0
        active_idx = -1
        for i, seg in enumerate(self.segments):
            acc += seg["sec"]
            if self._elapsed_sec < acc:
                active_idx = i
                break

        for i, seg in enumerate(self.segments):
            row = tk.Frame(self.legend, bg=BG_DARK)
            row.pack(fill="x", pady=1)
            dot = tk.Canvas(row, width=8, height=8, bg=BG_DARK, highlightthickness=0)
            dot.create_oval(0, 0, 8, 8, fill=seg["color"], outline="")
            dot.pack(side="left", padx=(0, 4))
            is_active = (i == active_idx)
            marker = " ◀" if is_active and self._running else ""
            tk.Label(row, text=seg["name"] + marker,
                     bg=BG_DARK,
                     fg=TEXT_MAIN if is_active else TEXT_DIM,
                     font=("Helvetica", 9, "bold" if is_active else "normal")
                     ).pack(side="left")
            tk.Label(row, text=fmt_min(seg["min"]),
                     bg=BG_DARK, fg=TEXT_DIM,
                     font=("Helvetica", 9)).pack(side="right")

    def refresh(self):
        self._draw()

    def _show_control(self):
        self.control.deiconify()
        self.control.lift()


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = FloatingWidget()
    app.mainloop()