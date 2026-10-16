"""Chinese desktop audio tag editor. Run with Python 3.10 or newer."""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import uuid
from windows_text_input import WindowsTextInput

from audio_metadata import (AudioRecord, BackupRecord, EXTENSIONS, FIELDS, discover_files,
                            duration_text, plan_changes, read_audio, restore_audio, save_audio,
                            size_text)

BG = "#f3f5f9"
INK = "#17283f"
MUTED = "#63738b"
ACCENT = "#087f8c"


class AudioEditor(tk.Tk):
    def __init__(self):
        self.text_input = WindowsTextInput()
        super().__init__()
        self.ui_scale = max(1.0, self.winfo_fpixels("1i") / 96)
        self.title("音档工坊 · 批量音频信息编辑器 v1.1")
        width = min(round(1440 * self.ui_scale), round(self.winfo_screenwidth() * .94))
        height = min(round(900 * self.ui_scale), round(self.winfo_screenheight() * .90))
        self.geometry(f"{width}x{height}")
        self.minsize(min(width, round(1120 * self.ui_scale)), min(height, round(780 * self.ui_scale)))
        self.configure(bg=BG)
        self.records: dict[str, AudioRecord] = {}
        self.undo_records: list[BackupRecord] = []
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.errors: list[tuple[str, str]] = []
        self.sort_column = "filename"
        self.sort_reverse = False
        self.search = tk.StringVar()
        self.format_filter = tk.StringVar(value="全部格式")
        self.recursive = tk.BooleanVar(value=True)
        self.auto_title = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="准备就绪 · 添加音档或文件夹开始整理")
        self.checked = {key: tk.BooleanVar(value=False) for key in FIELDS}
        self.values = {key: tk.StringVar() for key in FIELDS}
        self.controls = []
        self._loading_values = False
        self._last_text_entry = None
        self._style()
        self._build()
        for key, variable in self.values.items():
            variable.trace_add("write", lambda *_args, field=key: self._field_changed(field))
        self.search.trace_add("write", lambda *_: self._render_table())
        self.format_filter.trace_add("write", lambda *_: self._render_table())
        self.bind("<Control-o>", lambda _: self.add_files())
        self.bind("<Control-s>", lambda _: self.preview_save())
        self.tree.bind("<Control-a>", self.select_all)
        self.tree.bind("<Delete>", lambda _: self.remove_selected())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._poll_id = self.after(80, self._poll)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        self.option_add("*Font", ("Microsoft YaHei UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Card.TLabel", background="white", foreground=INK)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("CardMuted.TLabel", background="white", foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("TButton", padding=(13, 9), background="white", foreground=INK, borderwidth=1)
        style.map("TButton", background=[("active", "#e7edf4")], foreground=[("disabled", "#97a2b3")])
        style.configure("Accent.TButton", background=ACCENT, foreground="white", borderwidth=0, padding=(14, 10))
        style.map("Accent.TButton", background=[("active", "#066b76"), ("disabled", "#abc7cb")], foreground=[("disabled", "white")])
        style.configure("TEntry", padding=7, fieldbackground="white", bordercolor="#dbe2ec")
        style.configure("TCombobox", padding=6)
        style.configure("TCheckbutton", background="white", foreground=INK, padding=(0, 3))
        style.configure("Treeview", background="white", fieldbackground="white", foreground=INK,
                        rowheight=round(38 * self.ui_scale), borderwidth=0, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", background="#eaf0f6", foreground=MUTED,
                        padding=(8, 11), font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#d9eff0")], foreground=[("selected", INK)])
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#e1e7ef", borderwidth=0)

    def _button(self, parent, text, command, **kwargs):
        button = ttk.Button(parent, text=text, command=command, **kwargs)
        self.controls.append(button)
        return button

    def _build(self):
        header = tk.Frame(self, bg=INK, padx=26, pady=20)
        header.pack(fill="x")
        tk.Label(header, text="♫  音档工坊", bg=INK, fg="white", font=("Microsoft YaHei UI", 23, "bold")).pack(side="left")
        tk.Label(header, text="让每一首歌的信息，都井井有条。", bg=INK, fg="#aebed3", padx=24).pack(side="left")
        tk.Label(header, text="本地处理  /  自动备份", bg=INK, fg="#91dbd8", font=("Microsoft YaHei UI", 10)).pack(side="right")

        stats = ttk.Frame(self, padding=(26, 16))
        stats.pack(fill="x")
        self.count_label = ttk.Label(stats, text="0 首音档", font=("Microsoft YaHei UI", 17, "bold"))
        self.count_label.pack(side="left")
        self.summary_label = ttk.Label(stats, text="尚未添加文件", style="Muted.TLabel", padding=(22, 0))
        self.summary_label.pack(side="left")
        self._button(stats, "添加文件", self.add_files, style="Accent.TButton").pack(side="right", padx=(10, 0))
        self._button(stats, "添加文件夹", self.add_folder).pack(side="right")

        body = ttk.Frame(self, padding=(26, 0, 26, 12))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        library = ttk.Frame(body, style="Card.TFrame", padding=16)
        library.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        library.columnconfigure(0, weight=1)
        library.rowconfigure(2, weight=1)
        tools = ttk.Frame(library, style="Card.TFrame")
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(tools, text="音档资料库", style="Card.TLabel", font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        self._button(tools, "全选", self.select_all).pack(side="right")
        self._button(tools, "移出列表", self.remove_selected).pack(side="right", padx=6)
        self._button(tools, "刷新信息", self.refresh_selected).pack(side="right")

        filters = ttk.Frame(library, style="Card.TFrame")
        filters.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(filters, text="搜索", style="CardMuted.TLabel").pack(side="left", padx=(0, 8))
        search_entry = ttk.Entry(filters, textvariable=self.search)
        search_entry.bind("<FocusIn>", self._text_focus, add="+")
        search_entry.pack(side="left", fill="x", expand=True)
        self.controls.append(search_entry)
        self.format_box = ttk.Combobox(filters, textvariable=self.format_filter, values=["全部格式"], state="readonly", width=12)
        self.format_box.pack(side="left", padx=(10, 0))
        self.controls.append(self.format_box)

        table_frame = ttk.Frame(library, style="Card.TFrame")
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        columns = {"filename": ("文件名", 200), "title": ("标题", 170), "artist": ("歌手", 120),
                   "album": ("专辑", 140), "genre": ("曲风", 90), "format": ("格式", 85),
                   "bitrate": ("码率", 100), "duration": ("时长", 75), "sample_rate": ("采样率", 100), "size": ("大小", 90)}
        self.tree = ttk.Treeview(table_frame, columns=list(columns), show="headings", selectmode="extended")
        for key, (label, width) in columns.items():
            self.tree.heading(key, text=label, command=lambda col=key: self._sort(col))
            self.tree.column(key, width=round(width * self.ui_scale), minwidth=round(65 * self.ui_scale), stretch=key in ("filename", "title"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.tag_configure("alternate", background="#f8fafc")
        self.tree.bind("<<TreeviewSelect>>", lambda _: self._selection_changed())
        self.empty = tk.Label(table_frame, text="♫\n\n把你的音乐收藏带进来\n\n添加文件或文件夹，开始批量整理\n支持 MP3 · FLAC · M4A · WAV · OGG · OPUS · AIFF · WMA",
                              bg="white", fg=MUTED, font=("Microsoft YaHei UI", 11), justify="center")
        self.empty.place(relx=.5, rely=.46, anchor="center")
        ttk.Label(library, text="Ctrl / Shift 多选  ·  点击列名排序  ·  移出列表不会删除文件", style="CardMuted.TLabel").grid(row=3, column=0, sticky="w", pady=(12, 0))

        sidebar = ttk.Frame(body, style="Card.TFrame", padding=12)
        sidebar.grid(row=0, column=1, sticky="nsew")
        sidebar.rowconfigure(0, weight=1)
        sidebar.columnconfigure(0, weight=1)
        editor_canvas = tk.Canvas(sidebar, bg="white", width=round(365 * self.ui_scale), height=round(430 * self.ui_scale), highlightthickness=0)
        editor_canvas.grid(row=0, column=0, sticky="nsew")
        editor_scroll = ttk.Scrollbar(sidebar, orient="vertical", command=editor_canvas.yview)
        editor_scroll.grid(row=0, column=1, sticky="ns")
        editor_canvas.configure(yscrollcommand=editor_scroll.set)
        editor = ttk.Frame(editor_canvas, style="Card.TFrame", padding=8)
        editor_window = editor_canvas.create_window((0, 0), window=editor, anchor="nw")
        editor.bind("<Configure>", lambda _: editor_canvas.configure(scrollregion=editor_canvas.bbox("all")))
        editor_canvas.bind("<Configure>", lambda event: editor_canvas.itemconfigure(editor_window, width=event.width))
        def scroll_editor(event):
            if str(event.widget).startswith(str(sidebar)):
                editor_canvas.yview_scroll(int(-event.delta / 120), "units")
        self.bind("<MouseWheel>", scroll_editor, add="+")
        editor.columnconfigure(1, weight=1)
        ttk.Label(editor, text="批量编辑", style="Card.TLabel", font=("Microsoft YaHei UI", 15, "bold")).grid(row=0, column=0, sticky="w")
        self._button(editor, "中文输入", self.enable_chinese_input).grid(row=0, column=1, sticky="e")
        self.selection_label = ttk.Label(editor, text="先在左侧选择音档", style="CardMuted.TLabel")
        self.selection_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 12))
        ttk.Label(editor, text="勾选后留空即清除；自动补填将在确认保存后写入。", wraplength=round(340 * self.ui_scale), style="CardMuted.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 8))
        auto_title_check = ttk.Checkbutton(editor, text="空标题自动用文件名补填（去掉扩展名）", variable=self.auto_title, command=self._render_table)
        auto_title_check.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.controls.append(auto_title_check)
        self.entries = {}
        for row, (key, label) in enumerate(FIELDS.items(), start=4):
            check = ttk.Checkbutton(editor, text=label, variable=self.checked[key])
            check.grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
            entry = ttk.Entry(editor, textvariable=self.values[key], width=23)
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            entry.bind("<FocusIn>", self._text_focus, add="+")
            self.entries[key] = entry
            self.controls.extend((check, entry))
        ttk.Label(editor, text="日期：2026-10-16    编号：1/12\n多值会以「; 」显示；新内容作为单一文本写入。", style="CardMuted.TLabel").grid(row=14, column=0, columnspan=2, sticky="w", pady=(4, 10))
        self._button(editor, "重置待修改内容", self.reset_editor).grid(row=15, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Separator(editor).grid(row=16, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Label(editor, text="音档详情", style="Card.TLabel", font=("Microsoft YaHei UI", 10, "bold")).grid(row=17, column=0, columnspan=2, sticky="w")
        self.detail = tk.StringVar(value="选择音档查看编码、声道与文件位置。")
        ttk.Label(editor, textvariable=self.detail, style="CardMuted.TLabel", wraplength=round(335 * self.ui_scale), justify="left").grid(row=18, column=0, columnspan=2, sticky="nw", pady=(6, 10))
        self._button(sidebar, "预览并保存修改", self.preview_save, style="Accent.TButton").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        bottom = ttk.Frame(self, padding=(26, 0, 26, 12))
        ttk.Label(bottom, textvariable=self.status, style="Muted.TLabel").pack(side="left", fill="x", expand=True)
        self.cancel_button = ttk.Button(bottom, text="停止", command=self.cancel_event.set, state="disabled")
        self.cancel_button.pack(side="right", padx=(8, 0))
        self.undo_button = ttk.Button(bottom, text="撤销上次保存", command=self.undo, state="disabled")
        self.undo_button.pack(side="right", padx=(8, 0))
        self.error_button = ttk.Button(bottom, text="查看失败详情", command=self.show_errors, state="disabled")
        self.error_button.pack(side="right")
        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.progress.pack(side="bottom", fill="x")
        bottom.pack(side="bottom", fill="x")
        body.pack(fill="both", expand=True)

    def _field_changed(self, key):
        # IME commits and paste operations need not emit an ordinary KeyRelease.
        if not self._loading_values:
            self.checked[key].set(True)

    def _text_focus(self, event):
        self._last_text_entry = event.widget
        self.text_input.ensure_context(event.widget.winfo_id())

    def enable_chinese_input(self):
        if self.busy:
            return
        entry = self._last_text_entry or self.entries["artist"]
        entry.focus_set()
        _connected, message = self.text_input.enable_chinese(entry.winfo_id())
        self.status.set(message)

    def selected(self):
        return [self.records[key] for key in self.tree.selection() if key in self.records]

    def _sort(self, column):
        self.sort_reverse = not self.sort_reverse if self.sort_column == column else False
        self.sort_column = column
        self._render_table()

    def _render_table(self):
        selected = set(self.tree.selection())
        scroll = self.tree.yview()[0]
        query = self.search.get().strip().casefold()
        fmt = self.format_filter.get()
        records = [r for r in self.records.values() if (fmt == "全部格式" or r.format == fmt)
                   and (not query or query in (r.path.name + " " + " ".join(r.tags.values())).casefold())]
        def sort_key(record):
            key = self.sort_column
            if key == "filename":
                return record.path.name.casefold()
            if key == "size":
                return record.signature.size
            return record.tags[key].casefold() if key in FIELDS else getattr(record, key)
        records.sort(key=sort_key, reverse=self.sort_reverse)
        self.tree.delete(*self.tree.get_children())
        for index, record in enumerate(records):
            rate = f"{'≈' if record.bitrate_estimated else ''}{round(record.bitrate / 1000)} kbps" if record.bitrate else "—"
            self.tree.insert("", "end", iid=str(record.path), tags=("alternate",) if index % 2 else (), values=(
                record.path.name, (record.path.stem.strip() + "（待补填）") if self.auto_title.get() and not record.tags["title"].strip() else record.tags["title"] or "—", record.tags["artist"] or "—", record.tags["album"] or "—",
                record.tags["genre"] or "—", record.format, rate, duration_text(record.duration),
                f"{record.sample_rate / 1000:g} kHz" if record.sample_rate else "—", size_text(record.signature.size)))
        self.tree.selection_set([str(r.path) for r in records if str(r.path) in selected])
        self.tree.yview_moveto(scroll)
        self.empty.configure(text="♫\n\n把你的音乐收藏带进来\n\n添加文件或文件夹，开始批量整理\n支持 MP3 · FLAC · M4A · WAV · OGG · OPUS · AIFF · WMA" if not self.records else "没有匹配的音档\n\n试试其他关键词或格式")
        if records:
            self.empty.place_forget()
        else:
            self.empty.place(relx=.5, rely=.46, anchor="center")
        self.count_label.configure(text=f"{len(self.records)} 首音档")
        self.summary_label.configure(text=f"当前显示 {len(records)} 首   ·   总时长 {duration_text(sum(r.duration for r in self.records.values()))}")
        self.format_box.configure(values=["全部格式"] + sorted({r.format for r in self.records.values()}))
        self._selection_changed()

    def _selection_changed(self):
        selected = self.selected()
        self.selection_label.configure(text=f"已选择 {len(selected)} 首音档" if selected else "先在左侧选择音档")
        self._loading_values = True
        try:
            for key in FIELDS:
                if self.checked[key].get():
                    continue
                values = {(record.path.stem.strip() if key == "title" and self.auto_title.get() and not record.tags[key].strip()
                           else record.tags[key]) for record in selected}
                self.values[key].set(next(iter(values)) if len(values) == 1 else "")
        finally:
            self._loading_values = False
        if not selected:
            self.detail.set("选择音档查看编码、声道与文件位置。")
        elif len(selected) == 1:
            r = selected[0]
            channels = {1: "单声道", 2: "立体声"}.get(r.channels, f"{r.channels} 声道" if r.channels else "声道未知")
            bits = f" · {r.bits_per_sample} bit" if r.bits_per_sample else ""
            self.detail.set(f"{r.codec} · {channels}{bits}\n{duration_text(r.duration)} · {size_text(r.signature.size)}\n{r.path}")
        else:
            mixed = [label for key, label in FIELDS.items() if len({r.tags[key] for r in selected}) > 1]
            self.detail.set(f"共 {len(selected)} 首 · {duration_text(sum(r.duration for r in selected))}\n不同值的字段显示为空，未勾选时保留各自原值。\n不同值：{'、'.join(mixed) or '无'}")

    def reset_editor(self):
        if self.busy:
            return
        for var in self.checked.values():
            var.set(False)
        self._selection_changed()

    def select_all(self, _event=None):
        if not self.busy:
            self.tree.selection_set(self.tree.get_children())
        return "break"

    def remove_selected(self):
        if self.busy:
            return
        for key in self.tree.selection():
            self.records.pop(key, None)
        self._render_table()

    def add_files(self):
        if self.busy:
            return
        paths = filedialog.askopenfilenames(title="选择音档（可多选）", filetypes=[("音频文件", " ".join("*" + ext for ext in sorted(EXTENSIONS))), ("所有文件", "*.*")])
        if paths:
            self._scan(paths)

    def add_folder(self):
        if self.busy:
            return
        path = filedialog.askdirectory(title="选择音乐文件夹（包含子文件夹）")
        if path:
            self._scan([path])

    def _scan(self, paths):
        known = set(self.records)
        def work(emit):
            count = 0
            def on_error(error):
                emit("error", (str(error.filename), str(error)))
            for path in discover_files(paths, on_error=on_error):
                if self.cancel_event.is_set():
                    break
                if str(path) in known:
                    continue
                emit("status", f"正在读取：{path.name}")
                try:
                    emit("record", read_audio(path))
                    count += 1
                except Exception as error:
                    emit("error", (str(path), str(error)))
            return f"已添加 {count} 首音档"
        self._start(work, scanning=True)

    def refresh_selected(self):
        if self.busy:
            return
        records = self.selected() or list(self.records.values())
        if not records:
            return
        def work(emit):
            count = 0
            for index, record in enumerate(records, 1):
                if self.cancel_event.is_set():
                    break
                try:
                    emit("record", read_audio(record.path))
                    count += 1
                except Exception as error:
                    emit("error", (str(record.path), str(error)))
                emit("progress", (index, len(records)))
            return f"已刷新 {count} 首音档"
        self._start(work)

    def preview_save(self):
        if self.busy:
            return
        selected = self.selected()
        if not selected:
            messagebox.showinfo("选择音档", "请先在列表中选择要修改的音档。", parent=self)
            return
        try:
            changes = {key: self.values[key].get() for key in FIELDS if self.checked[key].get()}
            targets = plan_changes(selected, changes, fill_empty_titles=self.auto_title.get())
        except ValueError as error:
            messagebox.showwarning("检查修改内容", str(error), parent=self)
            return
        if not targets:
            messagebox.showinfo("无需修改", "所选音档没有需要保存的修改。", parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.title("保存前预览")
        dialog.geometry(f"{round(930 * self.ui_scale)}x{round(580 * self.ui_scale)}")
        dialog.minsize(round(700 * self.ui_scale), round(400 * self.ui_scale))
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(dialog, text=f"即将修改 {len(targets)} 首音档", font=("Microsoft YaHei UI", 16, "bold"), padding=20).pack(anchor="w")
        ttk.Label(dialog, text="留空的勾选字段将被清除。原文件会自动备份到音档所在目录的 .audio-tag-backups 文件夹。", padding=(20, 0, 20, 16)).pack(anchor="w")
        frame = ttk.Frame(dialog, padding=(20, 0))
        frame.pack(fill="both", expand=True)
        table = ttk.Treeview(frame, columns=("file", "field", "old", "new"), show="headings")
        for key, text in (("file", "文件名"), ("field", "修改字段"), ("old", "原内容"), ("new", "新内容")):
            table.heading(key, text=text)
            table.column(key, width=200 if key != "field" else 100)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        table.pack(fill="both", expand=True)
        for record, edits in targets:
            for key, value in edits.items():
                table.insert("", "end", values=(record.path.name, FIELDS[key], record.tags[key] or "（空）", value or "（清除）"))
        actions = ttk.Frame(dialog, padding=20)
        actions.pack(fill="x")
        def confirm():
            dialog.destroy()
            self._save_targets(targets)
        ttk.Button(actions, text="确认保存", style="Accent.TButton", command=confirm).pack(side="right")
        ttk.Button(actions, text="返回编辑", command=dialog.destroy).pack(side="right", padx=10)

    def _save_targets(self, targets):
        batch_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        def work(emit):
            backups = []
            for index, (record, edits) in enumerate(targets, 1):
                if self.cancel_event.is_set():
                    break
                emit("status", f"正在保存 {index}/{len(targets)}：{record.path.name}")
                try:
                    updated, backup = save_audio(record, edits, batch_id)
                    backups.append(backup)
                    emit("record", updated)
                except Exception as error:
                    emit("error", (str(record.path), str(error)))
                emit("progress", (index, len(targets)))
            if backups:
                emit("backups", backups)
            return f"已保存 {len(backups)} 首音档 · 原文件已自动备份"
        self._start(work)

    def undo(self):
        if self.busy or not self.undo_records:
            return
        if not messagebox.askyesno("撤销上次保存", f"将恢复上次保存的 {len(self.undo_records)} 首音档。继续吗？", parent=self):
            return
        backups = list(self.undo_records)
        def work(emit):
            remaining = []
            count = 0
            for index, backup in enumerate(backups, 1):
                if self.cancel_event.is_set():
                    remaining.extend(backups[index - 1:])
                    break
                try:
                    emit("record", restore_audio(backup))
                    count += 1
                except Exception as error:
                    remaining.append(backup)
                    emit("error", (str(backup.original), str(error)))
                emit("progress", (index, len(backups)))
            emit("backups", remaining)
            return f"已恢复 {count} 首音档 · 备份文件仍保留"
        self._start(work)

    def _start(self, work, scanning=False):
        self.busy = True
        self.errors = []
        self.cancel_event.clear()
        self.status.set("正在准备…")
        for widget in self.controls:
            widget.configure(state="disabled")
        self.undo_button.configure(state="disabled")
        self.error_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.configure(mode="indeterminate" if scanning else "determinate", value=0)
        if scanning:
            self.progress.start(12)
        def run():
            try:
                result = work(lambda kind, data: self.events.put((kind, data)))
            except Exception as error:
                self.events.put(("error", ("任务", str(error))))
                result = "操作未完成"
            self.events.put(("finished", result))
        threading.Thread(target=run, daemon=True).start()

    def _poll(self):
        # Bound each drain so huge libraries cannot starve Tk's event loop.
        for _ in range(150):
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "record":
                self.records[str(data.path)] = data
            elif kind == "error":
                self.errors.append(data)
            elif kind == "status":
                self.status.set(data)
            elif kind == "progress":
                self.progress.configure(value=data[0] / data[1] * 100)
            elif kind == "backups":
                self.undo_records = data
            elif kind == "finished":
                stopped = self.cancel_event.is_set()
                self.busy = False
                self.progress.stop()
                self.progress.configure(mode="determinate", value=0 if stopped else 100)
                for widget in self.controls:
                    widget.configure(state="normal")
                self.format_box.configure(state="readonly")
                self.cancel_button.configure(state="disabled")
                self.undo_button.configure(state="normal" if self.undo_records else "disabled")
                self.error_button.configure(state="normal" if self.errors else "disabled")
                self.status.set(("已停止 · " if stopped else "") + data + (f" · {len(self.errors)} 项失败（查看详情）" if self.errors else ""))
                self._render_table()
        self._poll_id = self.after(80, self._poll)

    def destroy(self):
        self.after_cancel(self._poll_id)
        self.text_input.close()
        super().destroy()

    def show_errors(self):
        dialog = tk.Toplevel(self)
        dialog.title("失败详情")
        dialog.geometry("800x420")
        text = tk.Text(dialog, wrap="word", padx=18, pady=18, bg="white", fg=INK)
        scroll = ttk.Scrollbar(dialog, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.insert("1.0", "\n\n".join(f"{path}\n原因：{error}" for path, error in self.errors))
        text.configure(state="disabled")

    def _close(self):
        if self.busy:
            self.cancel_event.set()
            messagebox.showinfo("正在停止", "将在当前文件处理完成后停止，请稍后再关闭窗口。", parent=self)
            return
        self.destroy()


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    AudioEditor().mainloop()


if __name__ == "__main__":
    main()
