"""Windows desktop UI for firmware inspection."""

from __future__ import annotations

import csv
import os
from pathlib import Path
import sys
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from firmware import Change, Firmware, FirmwareError, compare, load
from native_source_dialog import choose_source
from project_scan import EXTENSIONS, Artifact, ScanResult, ScanSession


def fmt_size(n: int) -> str:
    return f"{n:,} B  ({n / 1024:.2f} KiB)"


def hx(data: bytes, shortened: bool = False) -> str:
    return " ".join(f"{v:02X}" for v in data) + (" …" if shortened else "")


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("固件文件检查工具")
        icon = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets" / "firmware.ico"
        if icon.exists():
            try:
                self.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        self.geometry("1160x790")
        self.minsize(880, 620)
        self.configure(bg="#f3f6fa")
        self.files: list[Firmware | None] = [None, None]
        self.changes: list[Change] = []
        self.truncated = False
        self.vars = [{"path": tk.StringVar(), "base": tk.StringVar(value="0x08000000"), "info": tk.StringVar(value="请选择固件文件")}
                     for _ in range(2)]
        self.status = tk.StringVar(value="支持 BIN / Intel HEX / ELF / map；校验值针对原始文件。")
        self.summary = tk.StringVar(value="选择两个固件后，点击“按地址比较”。")
        self.project_path = tk.StringVar()
        self.project_summary = tk.StringVar(value="选择工程文件夹或 ZIP 压缩包，扫描后在下方查看结果。")
        self.project_result: ScanResult | None = None
        self.project_maps: dict[str, Firmware] = {}
        self.scan_queue: queue.Queue[tuple[int, str, object]] = queue.Queue()
        self.scan_running = False
        self.scan_id = 0
        self.scan_cancel = threading.Event()
        self.scan_session: ScanSession | None = None
        self.scan_source_key = ""
        self.scan_obsolete = False
        self.scan_after_picker = ""
        self.slow_tip = tk.StringVar()
        self._build()
        self.project_path.trace_add("write", self._on_project_path_changed)
        self.after(100, self._poll_scan)
        try:
            from win_drop import enable_file_drop
            self._drop_handler = enable_file_drop(self, self._dropped)
        except (ImportError, OSError, RuntimeError):
            self._drop_handler = None

    def _build(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", rowheight=27, font=("Consolas", 10), background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        root = tk.Frame(self, bg="#f3f6fa", padx=20, pady=16)
        root.pack(fill="both", expand=True)
        tk.Label(root, text="固件文件检查工具", font=("Microsoft YaHei UI", 19, "bold"), bg="#f3f6fa", fg="#14243a").pack(anchor="w")
        tk.Label(root, text="扫描工程产物 · 检查固件信息 · 按地址比较版本", font=("Microsoft YaHei UI", 10), bg="#f3f6fa", fg="#66788e").pack(anchor="w", pady=(2, 12))
        nav = tk.Frame(root, bg="#f3f6fa")
        nav.pack(fill="x", pady=(0, 12))
        self.nav_buttons = {}
        for key, label in (("project", "工程分析"), ("compare", "固件对比")):
            button = tk.Button(nav, text=label, font=("Microsoft YaHei UI", 11), bd=0, padx=20, pady=8,
                               cursor="hand2", command=lambda page=key: self._show_page(page))
            button.pack(side="left", padx=(0, 8))
            self.nav_buttons[key] = button
        pages = tk.Frame(root, bg="#f3f6fa")
        pages.pack(fill="both", expand=True)
        self.pages = {key: tk.Frame(pages, bg="#f3f6fa") for key in ("project", "compare")}
        for page in self.pages.values():
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._build_project(self.pages["project"])
        self._build_compare(self.pages["compare"])
        tk.Label(root, textvariable=self.status, bg="#f3f6fa", fg="#607087", anchor="w").pack(fill="x", pady=(9, 0))
        self._show_page("project")

    def _show_page(self, name: str) -> None:
        self.active_page = name
        self.pages[name].lift()
        for key, button in self.nav_buttons.items():
            button.configure(bg="#dcecf9" if key == name else "white", fg="#175d91" if key == name else "#45566a")

    def _build_compare(self, root: tk.Frame) -> None:
        tk.Label(root, text="把固件文件拖到左侧 A 或右侧 B；也可以一次拖入两个文件，依次作为 A、B。",
                 bg="#f3f6fa", fg="#66788e", anchor="w").pack(fill="x", pady=(0, 8))
        cards = tk.Frame(root, bg="#f3f6fa")
        cards.pack(fill="x")
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)
        self.compare_cards = []
        for side, title in enumerate(("旧版本 / 文件 A", "新版本 / 文件 B")):
            card = tk.Frame(cards, bg="white", highlightbackground="#d9e2ec", highlightthickness=1, padx=14, pady=12)
            card.grid(row=0, column=side, sticky="nsew", padx=(0, 7) if side == 0 else (7, 0))
            self.compare_cards.append(card)
            card.columnconfigure(0, weight=1)
            tk.Label(card, text=title, bg="white", fg="#193451", font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, sticky="w")
            row = tk.Frame(card, bg="white")
            row.grid(row=1, column=0, sticky="ew", pady=(10, 7))
            row.columnconfigure(0, weight=1)
            ttk.Entry(row, textvariable=self.vars[side]["path"]).grid(row=0, column=0, sticky="ew")
            ttk.Button(row, text="浏览…", command=lambda s=side: self._browse(s)).grid(row=0, column=1, padx=(8, 0))
            base = tk.Frame(card, bg="white")
            base.grid(row=2, column=0, sticky="w")
            tk.Label(base, text="BIN 加载基址", bg="white", fg="#53657a").pack(side="left")
            ttk.Entry(base, width=16, textvariable=self.vars[side]["base"]).pack(side="left", padx=8)
            ttk.Button(base, text="读取文件", command=lambda s=side: self._load(s)).pack(side="left")
            tk.Label(card, textvariable=self.vars[side]["info"], bg="white", fg="#24364b", font=("Consolas", 9), justify="left", anchor="nw", wraplength=500).grid(row=3, column=0, sticky="ew", pady=(12, 0))

        actions = tk.Frame(root, bg="#f3f6fa")
        actions.pack(fill="x", pady=(15, 8))
        ttk.Button(actions, text="按地址比较", command=self._compare).pack(side="left")
        ttk.Button(actions, text="导出差异 CSV", command=self._export).pack(side="left", padx=8)
        tk.Label(actions, textvariable=self.summary, bg="#f3f6fa", fg="#335a83", font=("Microsoft YaHei UI", 10)).pack(side="left", padx=14)

        table_frame = tk.Frame(root, bg="white", highlightbackground="#d9e2ec", highlightthickness=1)
        table_frame.pack(fill="both", expand=True)
        columns = ("kind", "start", "end", "size", "before", "after")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings")
        for key, label, width in (("kind", "类型", 80), ("start", "起始地址", 125), ("end", "结束地址", 125), ("size", "字节数", 85), ("before", "旧值（前 16 字节）", 250), ("after", "新值（前 16 字节）", 250)):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=70, stretch=key in ("before", "after"))
        scroll_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scroll_x = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.table.tag_configure("added", foreground="#08764a")
        self.table.tag_configure("removed", foreground="#b74434")
        self.table.tag_configure("modified", foreground="#a36800")

    def _build_project(self, root: tk.Frame) -> None:
        source = tk.Frame(root, bg="white", highlightbackground="#d9e2ec", highlightthickness=1, padx=14, pady=12)
        source.pack(fill="x")
        tk.Label(source, text="工程位置", bg="white", fg="#193451", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        row = tk.Frame(source, bg="white")
        row.pack(fill="x", pady=(8, 0))
        ttk.Entry(row, textvariable=self.project_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="选择文件", command=self._browse_project_source).pack(side="left", padx=(8, 0))
        self.scan_button = ttk.Button(row, text="开始扫描", command=self._scan_project)
        self.scan_button.pack(side="left", padx=(8, 0))
        self.cancel_button = ttk.Button(row, text="终止扫描", command=self._cancel_scan, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        tk.Label(source, text="可直接将文件夹或 ZIP 文件拖入此处，确认路径后点击“开始扫描”",
                 bg="white", fg="#66788e", anchor="w").pack(fill="x", pady=(9, 0))
        tk.Label(source, textvariable=self.slow_tip, bg="white", fg="#a36617", anchor="w").pack(fill="x", pady=(3, 0))
        tk.Label(root, textvariable=self.project_summary, bg="#f3f6fa", fg="#335a83", anchor="w",
                 font=("Microsoft YaHei UI", 10), wraplength=1000, justify="left").pack(fill="x", pady=(13, 8))
        table_frame = tk.Frame(root, bg="white", highlightbackground="#d9e2ec", highlightthickness=1)
        table_frame.pack(fill="both", expand=True)
        cols = ("file", "format", "file_size", "address", "image", "flash", "target", "version", "result")
        self.project_table = ttk.Treeview(table_frame, columns=cols, show="headings", height=12)
        for key, label, width in (("file", "文件", 240), ("format", "格式", 64), ("file_size", "文件大小", 100),
                                  ("address", "地址范围", 175), ("image", "镜像数据", 95), ("flash", "镜像 / 链接区上限", 195),
                                  ("target", "目标", 125), ("version", "版本", 100), ("result", "结果", 140)):
            self.project_table.heading(key, text=label)
            self.project_table.column(key, width=width, minwidth=60, stretch=key in ("file", "result"))
        vbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.project_table.yview)
        hbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.project_table.xview)
        self.project_table.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        self.project_table.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.project_table.bind("<<TreeviewSelect>>", self._select_artifact)
        tk.Label(root, text="选中文件查看校验值与说明", bg="#f3f6fa", fg="#53657a").pack(anchor="w", pady=(10, 4))
        detail_frame = tk.Frame(root, bg="white", highlightbackground="#d9e2ec", highlightthickness=1)
        detail_frame.pack(fill="x")
        self.project_detail = tk.Text(detail_frame, height=6, wrap="word", relief="flat", padx=10, pady=8,
                                      font=("Consolas", 9), bg="white", fg="#24364b")
        self.project_detail.pack(fill="x")
        self.project_detail.configure(state="disabled")

    def _initial_source_directory(self) -> str:
        value = self.project_path.get().strip().strip('"')
        if not value:
            return str(Path.home())
        current = Path(value)
        if current.is_dir():
            return str(current)
        if current.is_file():
            return str(current.parent)
        return str(Path.home())

    def _browse_project_source(self) -> None:
        try:
            path = choose_source(self.winfo_id(), self._initial_source_directory())
        except OSError as exc:
            messagebox.showerror("选择失败", str(exc), parent=self)
            return
        if path:
            self._set_project_source(path)
            if self.scan_running:
                if self.scan_obsolete or self.scan_cancel.is_set():
                    self.scan_after_picker = self._source_key(path)
            else:
                self._scan_project()

    def _set_project_source(self, path: str) -> None:
        self.project_path.set(path)
        if self.scan_running:
            if self.scan_obsolete:
                self.project_summary.set("已选择新位置，正在结束旧扫描；结束后点击“开始扫描”。")
                self.status.set("正在结束旧扫描…")
        else:
            self._update_scan_button()
            action = self.scan_button.cget("text")
            self.project_summary.set(f"已选择：{path}。点击“{action}”后读取文件。")
            self.status.set("已选择位置，等待开始扫描。")

    @staticmethod
    def _source_key(path: str) -> str:
        value = path.strip().strip('"')
        if not value:
            return ""
        try:
            return os.path.normcase(str(Path(value).resolve()))
        except (OSError, ValueError):
            return os.path.normcase(value)

    def _on_project_path_changed(self, *_args) -> None:
        self.scan_after_picker = ""
        if not self.scan_session or self._source_key(self.project_path.get()) == self.scan_source_key:
            return
        self.scan_obsolete = True
        if self.scan_running:
            self.scan_cancel.set()
            self.cancel_button.configure(state="disabled")
            self.status.set("位置已更改，正在结束原扫描…")
        else:
            self.scan_session = None
        self.project_result = None
        self.project_maps.clear()
        self.project_table.delete(*self.project_table.get_children())
        self._set_project_detail("")
        self.project_summary.set("位置已更改，请点击“开始扫描”。")
        self.scan_button.configure(text="开始扫描")

    def _update_scan_button(self) -> None:
        resumable = (self.scan_session is not None and not self.scan_session.finished and not self.scan_obsolete
                     and self._source_key(self.project_path.get()) == self.scan_source_key)
        self.scan_button.configure(text="继续扫描" if resumable else "开始扫描")

    def _dropped(self, paths: list[str]) -> None:
        if not paths:
            return
        if self.active_page == "compare":
            self._drop_compare_files(paths)
        else:
            self.scan_after_picker = ""
            self._set_project_source(paths[0])

    def _drop_compare_files(self, paths: list[str]) -> None:
        if len(paths) > 2:
            messagebox.showwarning("文件过多", "固件对比一次最多接收两个文件。")
            return
        if any(not Path(path).is_file() or Path(path).suffix.lower() not in EXTENSIONS for path in paths):
            messagebox.showwarning("不支持的文件", "请在对比页拖入 BIN、HEX、ELF 或 map 文件；文件夹和 ZIP 请放到工程分析页。")
            return
        if len(paths) == 2:
            assignments = list(enumerate(paths))
        else:
            x, y = self.winfo_pointerx(), self.winfo_pointery()
            target = next((side for side, card in enumerate(self.compare_cards)
                           if card.winfo_rootx() <= x < card.winfo_rootx() + card.winfo_width()
                           and card.winfo_rooty() <= y < card.winfo_rooty() + card.winfo_height()), None)
            if target is None:
                target = 0 if not self.vars[0]["path"].get().strip() else 1
            assignments = [(target, paths[0])]
        for side, path in assignments:
            self.vars[side]["path"].set(path)
            self._load(side)
        sides = "、".join("A" if side == 0 else "B" for side, _ in assignments)
        if all(self.files[side] is not None for side, _ in assignments):
            self.status.set(f"已将文件放入对比栏 {sides}。")

    def _scan_project(self) -> None:
        if self.scan_running:
            return
        source = self.project_path.get().strip().strip('"')
        if not source:
            messagebox.showwarning("缺少路径", "请选择文件夹、ZIP 或支持的固件文件。")
            return
        source_key = self._source_key(source)
        if (self.scan_session is None or self.scan_session.finished or self.scan_obsolete
                or source_key != self.scan_source_key):
            try:
                self.scan_session = ScanSession(source)
            except (OSError, FirmwareError, ValueError) as exc:
                self.project_summary.set(f"无法开始扫描：{exc}")
                self.status.set(f"无法开始扫描：{exc}")
                return
            self.scan_source_key = source_key
            self.project_result = self.scan_session.result
            self.project_maps.clear()
            self.project_table.delete(*self.project_table.get_children())
            self._set_project_detail("")
        session = self.scan_session
        self.scan_obsolete = False
        self.scan_id += 1
        run_id = self.scan_id
        cancel_event = threading.Event()
        self.scan_cancel = cancel_event
        self.scan_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.scan_running = True
        self.slow_tip.set("")
        self.project_summary.set("正在扫描并校验文件…")
        self.status.set(f"扫描中：{source}")
        self.after(8000, lambda: self._show_slow_tip(run_id))

        def worker() -> None:
            try:
                result = session.run(cancel=cancel_event,
                                      progress=lambda dirs, files: self.scan_queue.put((run_id, "progress", (dirs, files))),
                                      on_artifact=lambda index, artifact: self.scan_queue.put((run_id, "artifact", (index, artifact))))
                self.scan_queue.put((run_id, "done", result))
            except Exception as exc:
                self.scan_queue.put((run_id, "error", f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _cancel_scan(self) -> None:
        if self.scan_running:
            self.scan_after_picker = ""
            self.scan_cancel.set()
            self.cancel_button.configure(state="disabled")
            self.status.set("正在终止扫描…")
            self.project_summary.set("正在终止扫描，已找到的文件会保留在结果中。")

    def _show_slow_tip(self, run_id: int) -> None:
        if self.scan_running and self.scan_id == run_id and not self.scan_cancel.is_set():
            self.slow_tip.set("扫描时间过长？试试缩小扫描范围")

    def _poll_scan(self) -> None:
        processed = 0
        while processed < 100:
            try:
                run_id, kind, value = self.scan_queue.get_nowait()
            except queue.Empty:
                break
            processed += 1
            if run_id != self.scan_id:
                continue
            if kind == "progress":
                if not self.scan_obsolete and not self.scan_cancel.is_set():
                    dirs, files = value
                    self.status.set(f"扫描中：已查看 {dirs:,} 个目录，发现 {files:,} 个候选文件")
                    self._update_live_summary()
            elif kind == "artifact":
                if not self.scan_obsolete:
                    index, artifact = value
                    self._append_project_artifact(index, artifact)
                    self._update_live_summary()
            else:
                self.scan_button.configure(state="normal")
                self.cancel_button.configure(state="disabled")
                self.scan_running = False
                self.slow_tip.set("")
                if self.scan_obsolete:
                    self.scan_session = None
                    self.project_summary.set("位置已更改，请点击“开始扫描”。")
                    self.status.set("原扫描已结束，请开始扫描新位置。")
                elif kind == "error":
                    self.scan_session = None
                    self.project_summary.set(f"扫描失败：{value}")
                    self.status.set(f"扫描失败：{value}")
                else:
                    self._render_project(value)  # type: ignore[arg-type]
                self._update_scan_button()
                if self.scan_after_picker and self._source_key(self.project_path.get()) == self.scan_after_picker:
                    self.scan_after_picker = ""
                    self.after_idle(self._scan_project)
        self.after(30 if processed == 100 else 100, self._poll_scan)

    def _update_live_summary(self) -> None:
        if self.scan_session:
            session = self.scan_session
            self.project_summary.set(f"正在扫描：已查看 {session.scanned_dirs:,} 个目录，已完成 {len(self.project_table.get_children()):,} 个文件。")

    def _project_row_values(self, artifact: Artifact) -> tuple:
        fw = artifact.firmware
        if not fw:
            return (artifact.name, "—", "—", "—", "—", "—", "—", "—", "解析失败")
        used, capacity, _ = self._flash_values(artifact.name, fw)
        flash = f"{used:,} / {capacity:,} B" if used is not None and capacity else \
                f"{used:,} B / 上限未知" if used is not None else "未识别"
        return (artifact.name, fw.kind, f"{fw.file_size:,} B", fw.address_range,
                f"{fw.image_size:,} B" if fw.kind != "MAP" else "—", flash,
                fw.target, fw.version, "已解析")

    def _append_project_artifact(self, index: int, artifact: Artifact) -> None:
        fw = artifact.firmware
        if fw and fw.kind == "MAP":
            key = Path(artifact.name).with_suffix("").as_posix().casefold()
            self.project_maps[key] = fw
        if self.project_table.exists(str(index)):
            self.project_table.item(str(index), values=self._project_row_values(artifact))
        else:
            self.project_table.insert("", "end", iid=str(index), values=self._project_row_values(artifact))
        if fw and fw.kind == "MAP" and self.project_result:
            for row in self.project_table.get_children():
                other = self.project_result.artifacts[int(row)]
                if Path(other.name).with_suffix("").as_posix().casefold() == key:
                    self.project_table.item(row, values=self._project_row_values(other))
        if index == 0:
            self.project_table.selection_set("0")

    def _render_project(self, result: ScanResult) -> None:
        self.project_result = result
        self.project_maps = {Path(a.name).with_suffix("").as_posix().casefold(): a.firmware
                             for a in result.valid if a.firmware and a.firmware.kind == "MAP"}
        counts: dict[str, int] = {}
        for index, artifact in enumerate(result.artifacts):
            fw = artifact.firmware
            if fw:
                counts[fw.kind] = counts.get(fw.kind, 0) + 1
            row = str(index)
            values = self._project_row_values(artifact)
            if self.project_table.exists(row):
                self.project_table.item(row, values=values)
            else:
                self.project_table.insert("", "end", iid=row, values=values)
        formats = "、".join(f"{key} {value}" for key, value in sorted(counts.items())) or "无"
        failures = len(result.artifacts) - len(result.valid)
        prefix = "扫描已终止。" if result.cancelled else "扫描完成。"
        message = f"{prefix} 已列出 {len(result.artifacts)} 个候选文件，成功解析 {len(result.valid)} 个，失败 {failures} 个。格式：{formats}。"
        if result.warnings:
            message += "  " + " ".join(result.warnings)
        if result.valid:
            message += "  同一工程的 BIN/HEX/ELF 可能是同一固件的不同格式，不能把大小相加。"
        self.project_summary.set(message)
        self.status.set(f"{'扫描已终止' if result.cancelled else '扫描完成'}：{result.source}")
        if result.artifacts and not self.project_table.selection():
            self.project_table.selection_set("0")
        elif self.project_table.selection():
            self._select_artifact()

    def _flash_values(self, name: str, fw: Firmware) -> tuple[int | None, int | None, str]:
        companion = self.project_maps.get(Path(name).with_suffix("").as_posix().casefold())
        capacity = fw.flash_capacity or (companion.flash_capacity if companion else None)
        used = fw.flash_used if fw.kind == "MAP" else fw.image_size
        source = "当前 map" if fw.kind == "MAP" else "同名 map" if companion and companion.flash_capacity else ""
        return used, capacity, source

    def _set_project_detail(self, text: str) -> None:
        self.project_detail.configure(state="normal")
        self.project_detail.delete("1.0", "end")
        self.project_detail.insert("1.0", text)
        self.project_detail.configure(state="disabled")

    def _select_artifact(self, _event=None) -> None:
        if not self.project_result or not self.project_table.selection():
            return
        artifact = self.project_result.artifacts[int(self.project_table.selection()[0])]
        fw = artifact.firmware
        if not fw:
            self._set_project_detail(f"{artifact.name}\n解析失败：{artifact.error}")
            return
        lines = [artifact.name, f"格式：{fw.kind}    文件大小：{fmt_size(fw.file_size)}    地址：{fw.address_range}",
                 f"镜像数据：{fmt_size(fw.image_size)}    目标：{fw.target}    版本：{fw.version}",
                 f"文件 CRC32：{fw.crc32}    文件 SHA-256：{fw.sha256}"]
        used, capacity, source = self._flash_values(artifact.name, fw)
        if capacity and used is not None:
            lines.append(f"镜像量 / 链接区上限：{fmt_size(used)} / {fmt_size(capacity)}  ({used / capacity:.1%})，上限来自{source}。")
        elif used is not None:
            lines.append(f"镜像量：{fmt_size(used)}；链接区上限未识别，无法计算占用百分比。")
        if fw.map_sections:
            lines.append("map 输出节：" + ", ".join(f"{name} {size:,} B" for name, _, size in fw.map_sections[:12]))
        lines.extend(fw.notes)
        self._set_project_detail("\n".join(lines))

    def _browse(self, side: int) -> None:
        path = filedialog.askopenfilename(title="选择固件或 map 文件", filetypes=[("固件与 map", "*.bin *.hex *.ihx *.elf *.axf *.out *.map"), ("所有文件", "*.*")])
        if path:
            self.vars[side]["path"].set(path)
            self._load(side)

    def _load(self, side: int) -> None:
        path = self.vars[side]["path"].get().strip().strip('"')
        if not path:
            messagebox.showwarning("缺少文件", "请先选择文件。")
            return
        try:
            base = int(self.vars[side]["base"].get().strip(), 0)
            fw = load(path, base)
        except (OSError, FirmwareError, ValueError) as exc:
            self.files[side] = None
            self.vars[side]["info"].set(f"读取失败：{exc}")
            self.status.set(f"读取失败：{exc}")
            return
        self.files[side] = fw
        fields = [f"格式：{fw.kind}    文件大小：{fmt_size(fw.file_size)}",
                  f"地址范围：{fw.address_range}",
                  f"镜像数据：{fmt_size(fw.image_size)}    段数：{len(fw.segments)}",
                  f"目标：{fw.target}    版本：{fw.version}",
                  f"CRC32：{fw.crc32}    SHA-256：{fw.sha256}"]
        if fw.flash_capacity:
            used = fw.flash_used or 0
            fields.append(f"镜像量 / 链接区上限：{fmt_size(used)} / {fmt_size(fw.flash_capacity)}  ({used / fw.flash_capacity:.1%})")
        elif fw.segments:
            fields.append(f"镜像量：{fmt_size(fw.image_size)}（链接区上限未知；可能含 RAM 初始化数据）")
        if fw.map_sections:
            sections = ", ".join(f"{name}={size:,}B" for name, _, size in fw.map_sections[:8])
            fields.append(f"map 输出节：{sections}" + (" …" if len(fw.map_sections) > 8 else ""))
        fields.extend(fw.notes)
        self.vars[side]["info"].set("\n".join(fields))
        self.status.set(f"已读取：{Path(path).name}")
        self._clear_comparison()

    def _clear_comparison(self) -> None:
        self.changes = []
        self.truncated = False
        self.table.delete(*self.table.get_children())
        self.summary.set("选择两个固件后，点击“按地址比较”。")

    def _compare(self) -> None:
        for side in (0, 1):
            self._load(side)
        if not all(self.files):
            return
        try:
            changes, totals, truncated = compare(self.files[0], self.files[1])  # type: ignore[arg-type]
        except FirmwareError as exc:
            messagebox.showerror("无法比较", str(exc))
            return
        self.changes = changes
        self.truncated = truncated
        self.table.delete(*self.table.get_children())
        labels = {"added": "新增", "removed": "删除", "modified": "修改"}
        for c in changes:
            self.table.insert("", "end", values=(labels[c.kind], f"0x{c.start:08X}", f"0x{c.end-1:08X}", f"{c.size:,}", hx(c.before, c.size > 16), hx(c.after, c.size > 16)), tags=(c.kind,))
        self.summary.set(f"新增 {totals['added']:,} B · 删除 {totals['removed']:,} B · 修改 {totals['modified']:,} B · 显示 {len(changes):,} 段" + ("（已达显示上限）" if truncated else ""))
        self.status.set("比较完成。地址仅统计实际存在的镜像字节；空洞不计入差异。")

    def _export(self) -> None:
        if not self.changes:
            messagebox.showinfo("没有差异", "请先比较两个固件文件。")
            return
        if self.truncated:
            messagebox.showwarning("导出范围", "差异段数超过 10,000；CSV 只包含当前显示的前 10,000 段。")
        path = filedialog.asksaveasfilename(title="导出差异", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["类型", "起始地址", "结束地址", "字节数", "旧值（前16字节）", "新值（前16字节）"])
                for c in self.changes:
                    writer.writerow([{"added": "新增", "removed": "删除", "modified": "修改"}[c.kind], f"0x{c.start:08X}", f"0x{c.end-1:08X}", c.size, hx(c.before, c.size > 16), hx(c.after, c.size > 16)])
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        self.status.set(f"已导出：{path}")


if __name__ == "__main__":
    App().mainloop()
