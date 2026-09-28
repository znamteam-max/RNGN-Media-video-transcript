from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

import desktop_app
import desktop_v7  # noqa: F401  # keeps robust chunked transcription engine active

APP_VERSION = "1.3.0"
desktop_app.APP_NAME = f"ZNAMBO Transcriber v{APP_VERSION}"

# Premium dark palette inspired by the approved mockup.
BG = "#070B12"
PANEL = "#0E1420"
PANEL_2 = "#111927"
PANEL_3 = "#0B111B"
BORDER = "#202B3C"
BORDER_SOFT = "#182334"
TEXT = "#F5F7FB"
TEXT_2 = "#A6B0C2"
TEXT_3 = "#6E7B90"
PURPLE = "#7C4DFF"
PURPLE_HOVER = "#8B61FF"
BLUE = "#397BFF"
GREEN = "#43D17C"
ORANGE = "#F3A24D"


def _hover(widget: tk.Widget, normal: str, hover: str) -> None:
    widget.bind("<Enter>", lambda _e: widget.configure(bg=hover), add="+")
    widget.bind("<Leave>", lambda _e: widget.configure(bg=normal), add="+")


def _card(parent, *, bg: str = PANEL, border: str = BORDER, pad: int = 1):
    shell = tk.Frame(parent, bg=border, bd=0, highlightthickness=0)
    inner = tk.Frame(shell, bg=bg, bd=0, highlightthickness=0)
    inner.pack(fill="both", expand=True, padx=pad, pady=pad)
    return shell, inner


def _action_button(
    parent,
    *,
    title: str,
    subtitle: str,
    icon: str,
    accent: str,
    command,
    state: str = "normal",
):
    btn = tk.Button(
        parent,
        text=f"{icon}   {title}\n      {subtitle}",
        command=command,
        state=state,
        justify="left",
        anchor="w",
        padx=18,
        pady=13,
        bd=0,
        relief="flat",
        bg=PANEL_2,
        fg=TEXT,
        activebackground="#182236",
        activeforeground=TEXT,
        disabledforeground="#586477",
        font=("Segoe UI", 10),
        cursor="hand2",
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=BORDER,
    )
    # Tk cannot style the subtitle independently, so use a restrained two-line tile.
    _hover(btn, PANEL_2, "#182236")
    btn._znambo_accent = accent  # type: ignore[attr-defined]
    return btn


def premium_build_ui(self) -> None:
    root = self.root
    root.geometry("1180x760")
    root.minsize(1080, 700)
    root.configure(bg=BG)

    try:
        root.tk.call("tk", "scaling", 1.05)
    except Exception:
        pass

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(
        "Premium.TCombobox",
        fieldbackground=PANEL_3,
        background=PANEL_3,
        foreground=TEXT,
        arrowcolor=TEXT_2,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        insertcolor=TEXT,
        padding=10,
        relief="flat",
    )
    style.map(
        "Premium.TCombobox",
        fieldbackground=[("readonly", PANEL_3)],
        foreground=[("readonly", TEXT)],
        selectbackground=[("readonly", PANEL_3)],
        selectforeground=[("readonly", TEXT)],
    )
    style.configure(
        "Premium.Horizontal.TProgressbar",
        troughcolor="#182131",
        background=BLUE,
        bordercolor="#182131",
        lightcolor=BLUE,
        darkcolor=PURPLE,
        thickness=8,
    )

    outer = tk.Frame(root, bg=BG)
    outer.pack(fill="both", expand=True, padx=18, pady=16)
    outer.grid_columnconfigure(0, weight=0, minsize=355)
    outer.grid_columnconfigure(1, weight=1)
    outer.grid_rowconfigure(0, weight=1)

    # LEFT: brand and all controls.
    left_shell, left = _card(outer, bg=PANEL, border=BORDER)
    left_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 10))
    left.configure(padx=28, pady=26)

    wave = tk.Canvas(left, width=70, height=38, bg=PANEL, highlightthickness=0)
    wave.pack(anchor="w", pady=(2, 18))
    pts = [(5, 20), (13, 20), (17, 10), (21, 29), (27, 5), (33, 32), (39, 9), (45, 27), (51, 14), (57, 20), (67, 20)]
    for a, b in zip(pts, pts[1:]):
        wave.create_line(a[0], a[1], b[0], b[1], fill=PURPLE, width=3, smooth=True)

    tk.Label(
        left,
        text="ZNAMBO —",
        bg=PANEL,
        fg=TEXT,
        font=("Segoe UI", 28, "bold"),
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        left,
        text="транскрибация",
        bg=PANEL,
        fg=TEXT,
        font=("Segoe UI", 27, "bold"),
        anchor="w",
    ).pack(fill="x", pady=(0, 14))
    tk.Label(
        left,
        text="Аудио или видео → готовый TXT\nавтоматически в Downloads.",
        bg=PANEL,
        fg=TEXT_2,
        font=("Segoe UI", 10),
        justify="left",
        anchor="w",
    ).pack(fill="x", pady=(0, 20))

    tk.Frame(left, bg=BORDER, height=1).pack(fill="x", pady=(0, 20))

    tk.Label(left, text="◎  Язык", bg=PANEL, fg=TEXT_2, font=("Segoe UI", 10)).pack(anchor="w")
    ttk.Combobox(
        left,
        textvariable=self.language,
        values=list(desktop_app.LANGUAGES),
        state="readonly",
        style="Premium.TCombobox",
        font=("Segoe UI", 10),
    ).pack(fill="x", pady=(7, 17))

    tk.Label(left, text="◉  Режим", bg=PANEL, fg=TEXT_2, font=("Segoe UI", 10)).pack(anchor="w")
    ttk.Combobox(
        left,
        textvariable=self.profile,
        values=list(desktop_app.MODEL_PROFILES),
        state="readonly",
        style="Premium.TCombobox",
        font=("Segoe UI", 10),
    ).pack(fill="x", pady=(7, 16))

    check = tk.Checkbutton(
        left,
        text="Добавить таймкоды в TXT",
        variable=self.timestamps,
        bg=PANEL,
        fg=TEXT_2,
        activebackground=PANEL,
        activeforeground=TEXT,
        selectcolor=PANEL_3,
        font=("Segoe UI", 10),
        bd=0,
        highlightthickness=0,
        cursor="hand2",
    )
    check.pack(anchor="w", pady=(2, 18))

    self.start_button = tk.Button(
        left,
        text="✦   Начать транскрибацию",
        command=self._start,
        bg=PURPLE,
        fg="white",
        activebackground=PURPLE_HOVER,
        activeforeground="white",
        disabledforeground="#A394D4",
        bd=0,
        relief="flat",
        padx=18,
        pady=14,
        font=("Segoe UI", 11, "bold"),
        cursor="hand2",
    )
    self.start_button.pack(fill="x", pady=(0, 4))
    _hover(self.start_button, PURPLE, PURPLE_HOVER)

    # RIGHT: hero drag/drop zone.
    right_shell, right = _card(outer, bg="#0A101B", border=BORDER)
    right_shell.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 10))
    right.configure(padx=34, pady=30)

    hero = tk.Frame(right, bg="#0A101B")
    hero.pack(fill="both", expand=True)

    file_icon = tk.Canvas(hero, width=110, height=105, bg="#0A101B", highlightthickness=0)
    file_icon.pack(pady=(70, 14))
    file_icon.create_polygon(31, 11, 69, 11, 88, 30, 88, 90, 31, 90, fill="#121A2A", outline=PURPLE, width=2)
    file_icon.create_line(69, 11, 69, 30, 88, 30, fill=PURPLE, width=2)
    file_icon.create_line(45, 57, 51, 57, 55, 44, 60, 71, 66, 48, 72, 62, 80, 62, fill=PURPLE, width=3, smooth=True)

    self.drop_zone = tk.Label(
        hero,
        text="ПЕРЕТАЩИ ФАЙЛ СЮДА",
        bg="#0A101B",
        fg=TEXT,
        font=("Segoe UI", 19, "bold"),
        justify="center",
        cursor="hand2",
    )
    self.drop_zone.pack(fill="x", pady=(4, 5))
    self.drop_zone.bind("<Button-1>", lambda _e: self._choose_file())
    self.drop_zone.drop_target_register(desktop_app.DND_FILES)
    self.drop_zone.dnd_bind("<<Drop>>", self._on_drop)
    root.drop_target_register(desktop_app.DND_FILES)
    root.dnd_bind("<<Drop>>", self._on_drop)

    tk.Label(
        hero,
        text="или выбери файл на компьютере",
        bg="#0A101B",
        fg=TEXT_2,
        font=("Segoe UI", 11),
    ).pack(pady=(0, 20))

    browse = tk.Button(
        hero,
        text="▢   Выбрать файл",
        command=self._choose_file,
        bg=PANEL_2,
        fg=TEXT,
        activebackground="#1A2440",
        activeforeground=TEXT,
        bd=0,
        relief="flat",
        padx=30,
        pady=12,
        font=("Segoe UI", 11),
        cursor="hand2",
        highlightthickness=1,
        highlightbackground="#6245C5",
        highlightcolor="#6245C5",
    )
    browse.pack(pady=(0, 14))
    _hover(browse, PANEL_2, "#1A2440")

    tk.Label(
        hero,
        text="M4A  ·  MP3  ·  WAV  ·  MP4  ·  и другие аудио/видео форматы",
        bg="#0A101B",
        fg=TEXT_3,
        font=("Segoe UI", 9),
    ).pack()

    # STATUS — full width between main content and footer tiles.
    status_shell, status_card = _card(outer, bg=PANEL_2, border=BORDER)
    status_shell.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
    status_card.configure(padx=22, pady=13)
    status_card.grid_columnconfigure(1, weight=1)

    tk.Label(status_card, text="●", bg=PANEL_2, fg=GREEN, font=("Segoe UI", 17)).grid(row=0, column=0, rowspan=2, padx=(0, 12), sticky="n")
    tk.Label(
        status_card,
        textvariable=self.status,
        bg=PANEL_2,
        fg=TEXT,
        font=("Segoe UI", 10, "bold"),
        anchor="w",
    ).grid(row=0, column=1, sticky="ew")
    tk.Label(
        status_card,
        textvariable=self.device,
        bg=PANEL_2,
        fg=TEXT_2,
        font=("Segoe UI", 9),
        anchor="w",
    ).grid(row=1, column=1, sticky="ew", pady=(2, 7))

    self.progress = ttk.Progressbar(
        status_card,
        maximum=100,
        mode="determinate",
        style="Premium.Horizontal.TProgressbar",
    )
    self.progress.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 0))

    badge = tk.Label(
        status_card,
        text="ГОТОВО",
        bg=PANEL_3,
        fg=TEXT_2,
        font=("Segoe UI", 8, "bold"),
        padx=12,
        pady=5,
        highlightthickness=1,
        highlightbackground=BORDER,
    )
    badge.grid(row=0, column=2, rowspan=2, padx=(18, 0), sticky="e")

    # FOOTER ACTION TILES.
    footer = tk.Frame(outer, bg=BG)
    footer.grid(row=2, column=0, columnspan=2, sticky="ew")
    for col in range(4):
        footer.grid_columnconfigure(col, weight=1, uniform="actions")

    self.open_file_button = _action_button(
        footer,
        title="Открыть TXT",
        subtitle="Просмотреть файл",
        icon="▤",
        accent=PURPLE,
        command=self._open_result,
        state="disabled",
    )
    self.open_file_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

    downloads = _action_button(
        footer,
        title="Открыть Downloads",
        subtitle="Папка с результатами",
        icon="▱",
        accent=BLUE,
        command=lambda: desktop_app.open_folder(desktop_app.DOWNLOAD_DIR),
    )
    downloads.grid(row=0, column=1, sticky="ew", padx=6)

    self.gpu_button = _action_button(
        footer,
        title="Настроить NVIDIA GPU",
        subtitle="Параметры ускорения",
        icon="◎",
        accent=GREEN,
        command=self._setup_gpu,
    )
    self.gpu_button.grid(row=0, column=2, sticky="ew", padx=6)

    logs = _action_button(
        footer,
        title="Логи",
        subtitle="Журнал работы",
        icon="≡",
        accent=ORANGE,
        command=lambda: desktop_app.open_folder(desktop_app.LOG_DIR),
    )
    logs.grid(row=0, column=3, sticky="ew", padx=(6, 0))


# Replace only the visual shell. All existing actions, event handling, GPU setup,
# drag-and-drop selection and robust chunked transcription remain untouched.
desktop_app.DesktopApp._build_ui = premium_build_ui


if __name__ == "__main__":
    logging.info("Starting ZNAMBO Transcriber v%s premium UI", APP_VERSION)
    desktop_app.DesktopApp().run()
