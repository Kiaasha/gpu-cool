#!/usr/bin/env python3
# GPU Cool: holds the NVIDIA GPU near a target temperature by moving its clock cap.
# Needs a sudoers rule that lets this user run "nvidia-smi -lgc" and "nvidia-smi -rgc" without a password.

import json
import math
import socket
import subprocess
import time
import tkinter as tk
from collections import deque
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3, GLib, Gtk

CONFIG = Path.home() / ".config" / "gpu_cool.json"
ICON = Path(__file__).with_name("gpu_cool.svg")
HISTORY = 300          # seconds shown on the chart
ADJUST_EVERY = 5       # seconds between clock cap changes
MIN_CLK = 600          # never cap the GPU below this (MHz)
T_MIN, T_MAX = 30, 95  # chart temperature range

BG, PANEL, FG, DIM = "#1e1f24", "#2a2c33", "#e6e6e6", "#8a8d96"
RED, BLUE, GREEN, AMBER, ORANGE = "#ff6b6b", "#5aa9ff", "#5ad18a", "#ffc861", "#ff9a5c"


def query(fields):
    out = subprocess.run(["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout
    return [float(v) for v in out.split(",")]


def pill(canvas, x1, y1, x2, y2, r, **kw):
    pts = (x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1)
    return canvas.create_polygon(pts, smooth=True, **kw)


def set_cap(clk):
    cmd = ["nvidia-smi", "-rgc"] if clk is None else ["nvidia-smi", "-lgc", f"300,{clk}"]
    return subprocess.run(["sudo", "-n"] + cmd, capture_output=True).returncode == 0


class App:
    def __init__(self, root):
        self.root = root
        self.max_clk, self.power_limit = (int(v) for v in query("clocks.max.gr,power.default_limit"))
        self.running = False
        self.cap = None
        self.tick = 0
        self.temps = deque(maxlen=HISTORY)
        self.clocks = deque(maxlen=HISTORY)
        self.powers = deque(maxlen=ADJUST_EVERY)
        cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}

        root.title("GPU Cool")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", root.withdraw)

        top = tk.Frame(root, bg=BG)
        top.pack(fill="x", padx=14, pady=(14, 6))
        self.big = tk.Label(top, text="--°C", font=("Sans", 30, "bold"), bg=BG, fg=FG)
        self.big.pack(side="left")
        self.info = tk.Label(top, text="", font=("Sans", 11), bg=BG, fg=DIM, justify="left")
        self.info.pack(side="left", padx=16)

        self.chart = tk.Canvas(root, width=560, height=220, bg=PANEL, highlightthickness=0)
        self.chart.pack(padx=14)

        self.mode = tk.StringVar(value=cfg.get("mode", "temp"))
        self.target = tk.IntVar(value=cfg.get("target", 70))
        self.target_pct = tk.IntVar(value=cfg.get("target_pct", 80))

        modes = tk.Frame(root, bg=BG)
        modes.pack(fill="x", padx=14, pady=(12, 0))
        tk.Label(modes, text="Hold", bg=BG, fg=DIM).pack(side="left", padx=(0, 8))
        self.selector = tk.Canvas(modes, width=250, height=34, bg=BG, highlightthickness=0, cursor="hand2")
        self.selector.pack(side="left")
        self.selector.bind("<Button-1>", lambda e: self.running or self.set_mode("temp" if e.x < 125 else "power"))

        slide = tk.Frame(root, bg=BG)
        slide.pack(fill="x", padx=14, pady=(8, 0))
        self.value_label = tk.Label(slide, width=12, font=("Sans", 14, "bold"), bg=BG, fg=FG, anchor="w")
        self.value_label.pack(side="left")
        self.slider = tk.Canvas(slide, width=470, height=30, bg=BG, highlightthickness=0, cursor="hand2")
        self.slider.pack(side="left")
        self.slider.bind("<Button-1>", self.drag)
        self.slider.bind("<B1-Motion>", self.drag)
        self.set_mode(self.mode.get())

        form = tk.Frame(root, bg=BG)
        form.pack(fill="x", padx=14, pady=12)
        self.overlay_on = tk.BooleanVar(value=cfg.get("overlay", True))
        tk.Checkbutton(form, text="Small display", variable=self.overlay_on, command=self.toggle_overlay,
                       bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, activeforeground=FG,
                       highlightthickness=0).pack(side="left", padx=(0, 12))
        self.button = tk.Button(form, text="Start", width=8, command=self.toggle, bg=GREEN, fg=BG,
                                activebackground=GREEN, relief="flat", font=("Sans", 11, "bold"))
        self.button.pack(side="right")
        tk.Button(form, text="Quit", width=6, command=self.quit, bg=PANEL, fg=FG, activebackground=PANEL,
                  activeforeground=FG, relief="flat").pack(side="right", padx=(0, 8))

        self.status = tk.Label(root, text="Monitoring only. Press Start to hold the target.",
                               font=("Sans", 10), bg=BG, fg=DIM, anchor="w")
        self.status.pack(fill="x", padx=14, pady=(0, 12))

        self.overlay = tk.Toplevel(root)
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.configure(bg="#000000")
        self.small = tk.Label(self.overlay, text="", font=("Sans", 11, "bold"), bg="#000000", fg=FG, padx=8, pady=3)
        self.small.pack()
        self.toggle_overlay()

        # tray icon next to the clock; menu callbacks are deferred to Tk so quit can destroy the window safely
        self.tray = AyatanaAppIndicator3.Indicator.new("gpu-cool", str(ICON),
                                                      AyatanaAppIndicator3.IndicatorCategory.HARDWARE)
        self.tray.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        menu = Gtk.Menu()
        for label, action in (("Show window", self.show), ("Quit", self.quit)):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _, action=action: root.after(0, action))
            menu.append(item)
        menu.show_all()
        self.tray.set_menu(menu)
        self.tray.set_secondary_activate_target(menu.get_children()[0])

        self.update()
        self.pump()

    def set_mode(self, mode):
        self.mode.set(mode)
        accent = ORANGE if mode == "temp" else BLUE
        # while running the selector is locked and dimmed; Stop first to change mode
        c = self.selector
        c.delete("all")
        c.config(cursor="arrow" if self.running else "hand2")
        pill(c, 1, 1, 249, 33, 16, fill="#15161a", outline="#454852")
        left = 4 if mode == "temp" else 126
        pill(c, left, 4, left + 120, 30, 13, fill=DIM if self.running else accent, outline="")
        for x, value, label in ((64, "temp", "Temperature"), (186, "power", "Power")):
            c.create_text(x, 17, text=label, font=("Sans", 10, "bold"),
                          fill=BG if value == mode else "#4a4d56" if self.running else DIM)
        self.accent = accent
        self.draw_slider()

    def slider_range(self):
        return (self.target, 60, 85, "°C") if self.mode.get() == "temp" else (self.target_pct, 50, 100, "%")

    def drag(self, e):
        var, lo, hi, _ = self.slider_range()
        frac = min(1, max(0, (e.x - 12) / (470 - 24)))
        var.set(lo + round(frac * (hi - lo) / 5) * 5)
        self.draw_slider()

    def draw_slider(self):
        var, lo, hi, unit = self.slider_range()
        x = 12 + (470 - 24) * (var.get() - lo) / (hi - lo)
        c = self.slider
        c.delete("all")
        c.create_line(12, 15, 458, 15, fill=PANEL, width=6, capstyle="round")
        c.create_line(12, 15, x, 15, fill=self.accent, width=6, capstyle="round")
        c.create_oval(x - 10, 5, x + 10, 25, fill=FG, outline=self.accent, width=3)
        text = f"{var.get()} {unit}" if unit == "°C" else f"{var.get()}%  ({self.target_watts()} W)"
        self.value_label.config(text=text, fg=self.accent)

    def target_watts(self):
        return round(self.power_limit * self.target_pct.get() / 100)

    def save(self):
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps({"mode": self.mode.get(), "target": self.target.get(),
                                      "target_pct": self.target_pct.get(), "overlay": self.overlay_on.get()}))

    def toggle_overlay(self):
        if self.overlay_on.get():
            self.overlay.deiconify()
        else:
            self.overlay.withdraw()

    def toggle(self):
        if self.running:
            set_cap(None)
            self.running, self.cap = False, None
            self.button.config(text="Start", bg=GREEN, activebackground=GREEN)
            self.status.config(text="Stopped. GPU is back to normal.", fg=DIM)
            self.set_mode(self.mode.get())
            return
        self.save()
        self.cap = self.max_clk
        if not set_cap(self.cap):
            self.cap = None
            self.status.config(text="No permission. Add the sudoers rule for nvidia-smi first.", fg=RED)
            return
        self.running = True
        self.button.config(text="Stop", bg=RED, activebackground=RED)
        self.set_mode(self.mode.get())

    def adjust(self, temp):
        if self.mode.get() == "temp":
            diff = temp - self.target.get()
            step = -100 if diff >= 4 else -50 if diff >= 1 else 50 if diff <= -3 else 0
        else:
            # power jumps around a lot, so steer on the average of the last few seconds,
            # in % of the card's own power limit so small and large GPUs behave the same
            diff = (sum(self.powers) / len(self.powers) - self.target_watts()) * 100 / self.power_limit
            step = -100 if diff >= 13 else -50 if diff >= 3 else 50 if diff <= -7 else 0
        new = max(MIN_CLK, min(self.max_clk, self.cap + step))
        if new != self.cap and set_cap(new):
            self.cap = new

    def update(self):
        temp, power, clock = query("temperature.gpu,power.draw,clocks.gr")
        self.temps.append(temp)
        self.clocks.append(clock)
        self.powers.append(power)
        self.tick += 1
        if self.running:
            if self.tick % ADJUST_EVERY == 0:
                self.adjust(temp)
            goal = f"temperature at {self.target.get()} °C" if self.mode.get() == "temp" else f"power at {self.target_pct.get()}% ({self.target_watts()} W)"
            self.status.config(text=f"Holding {goal}.  Press Stop to change mode.", fg=DIM)

        color = RED if temp >= self.target.get() + 3 else AMBER if temp > self.target.get() else GREEN
        self.big.config(text=f"{temp:.0f}°C", fg=color)
        cap = f"{self.cap} MHz" if self.cap else "none"
        self.info.config(text=f"Power  {power:.0f} W\nClock  {clock:.0f} MHz\nCap    {cap}")
        self.small.config(text=f"GPU {temp:.0f}°C  {power:.0f}W", fg=color)
        self.tray.set_label(f"{temp:.0f}°C", "00°C")
        self.draw()
        self.move_overlay()
        self.root.after(1000, self.update)

    def draw(self):
        c = self.chart
        c.delete("all")
        w, h, pad = 560, 220, 30

        def ty(t):
            return h - pad + (pad * 2 - h) * (t - T_MIN) / (T_MAX - T_MIN)

        def cy(clk):
            return h - pad + (pad * 2 - h) * clk / self.max_clk

        for t in range(40, T_MAX + 1, 10):
            c.create_line(pad, ty(t), w - pad, ty(t), fill="#383a42")
            c.create_text(pad - 6, ty(t), text=str(t), fill=DIM, anchor="e", font=("Sans", 8))
        c.create_text(w - pad + 4, cy(self.max_clk), text=f"{self.max_clk}", fill=BLUE, anchor="w", font=("Sans", 7))
        if self.mode.get() == "temp":
            c.create_line(pad, ty(self.target.get()), w - pad, ty(self.target.get()), fill=GREEN, dash=(4, 3))

        x = lambda i: pad + (w - pad * 2) * i / (HISTORY - 1)
        for series, scale, color in ((self.clocks, cy, BLUE), (self.temps, ty, RED)):
            if len(series) > 1:
                points = [v for i, s in enumerate(series) for v in (x(i), scale(s))]
                c.create_line(points, fill=color, width=2)
        c.create_text(pad, 12, text="● temp °C", fill=RED, anchor="w", font=("Sans", 9))
        c.create_text(pad + 90, 12, text="● clock", fill=BLUE, anchor="w", font=("Sans", 9))
        c.create_text(pad + 160, 12, text="- - target", fill=GREEN, anchor="w", font=("Sans", 9))

    def move_overlay(self):
        # move a few pixels once a minute so the display never burns a fixed spot
        m = int(time.time() // 60)
        dx = round(15 * math.sin(m * 1.7))
        dy = round(12 * math.cos(m * 2.3))
        self.overlay.update_idletasks()
        x = self.root.winfo_screenwidth() - self.overlay.winfo_width() - 40 + dx
        self.overlay.geometry(f"+{x}+{60 + dy}")

    def pump(self):
        while GLib.MainContext.default().iteration(False):
            pass
        self.root.after(50, self.pump)

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def quit(self):
        if self.running:
            set_cap(None)
        self.save()
        self.root.destroy()


# only one copy runs; opening it again just brings the existing window back
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
try:
    sock.bind("\0gpu_cool")
except OSError:
    sock.connect("\0gpu_cool")
    raise SystemExit
sock.listen()

root = tk.Tk(className="gpucool")
app = App(root)
root.tk.createfilehandler(sock, tk.READABLE, lambda *_: (sock.accept()[0].close(), app.show()))
root.mainloop()
