"""Exercise the real Tk event loop and background worker without manual dialogs."""
from pathlib import Path
import os
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import AudioEditor
from audio_metadata import read_audio
from test_metadata import make_wav


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class DesktopTests(unittest.TestCase):
    def setUp(self):
        artifacts = Path(__file__).resolve().parents[1] / ".test-artifacts"
        artifacts.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=artifacts)
        self.root = Path(self.temp.name)
        self.app = AudioEditor()
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        self.temp.cleanup()

    def drain(self):
        deadline = time.monotonic() + 15
        while self.app.busy and time.monotonic() < deadline:
            self.app.update()
            time.sleep(.01)
        self.app.update()
        self.assertFalse(self.app.busy, "background worker timed out")

    def test_batch_scan_filter_preview_save_undo(self):
        for name in ("第一首.wav", "第二首.wav"):
            make_wav(self.root / name)
        (self.root / "损坏.mp3").write_bytes(b"broken")
        self.app._scan([self.root])
        self.drain()
        self.assertEqual(len(self.app.records), 2)
        self.assertEqual(len(self.app.errors), 1)
        self.app.search.set("第一首")
        self.app.update()
        self.assertEqual(len(self.app.tree.get_children()), 1)
        self.app.search.set("")
        self.app.select_all()
        self.app.update()
        self.app.values["artist"].set("测试歌手")
        self.app.checked["artist"].set(True)
        self.app.preview_save()
        self.app.update()
        dialogs = [widget for widget in self.app.winfo_children() if isinstance(widget, tk.Toplevel)]
        self.assertEqual(len(dialogs), 1)
        confirm = next(widget for widget in descendants(dialogs[0])
                       if widget.winfo_class() == "TButton" and widget.cget("text") == "确认保存")
        confirm.invoke()
        self.drain()
        self.assertEqual(len(self.app.undo_records), 2)
        self.assertFalse(self.app.errors)
        for record in self.app.records.values():
            self.assertEqual(read_audio(record.path).tags["artist"], "测试歌手")
        with patch("app.messagebox.askyesno", return_value=True):
            self.app.undo()
        self.drain()
        self.assertFalse(self.app.undo_records)
        for record in self.app.records.values():
            self.assertEqual(record.tags["artist"], "")

    def test_auto_title_preview_and_batch_save_without_checked_fields(self):
        from audio_metadata import save_audio
        for name in ("晴天.wav", "演唱会.live.wav", "保留标题.wav"):
            make_wav(self.root / name)
        existing = self.root / "保留标题.wav"
        save_audio(read_audio(existing), {"title": "真正的原标题"}, "setup")
        self.app._scan([self.root])
        self.drain()
        self.app.select_all()
        self.app.update()
        self.assertFalse(any(var.get() for var in self.app.checked.values()))
        for record in self.app.records.values():
            if record.path != existing:
                self.assertEqual(read_audio(record.path).tags["title"], "")
                self.assertIn("待补填", self.app.tree.item(str(record.path), "values")[1])
        self.app.preview_save()
        self.app.update()
        dialog = next(widget for widget in self.app.winfo_children() if isinstance(widget, tk.Toplevel))
        table = next(widget for widget in descendants(dialog) if widget.winfo_class() == "Treeview")
        edits = [table.item(item, "values") for item in table.get_children()]
        self.assertEqual(len(edits), 2)
        self.assertEqual({(row[0], row[3]) for row in edits}, {("晴天.wav", "晴天"), ("演唱会.live.wav", "演唱会.live")})
        next(widget for widget in descendants(dialog) if widget.winfo_class() == "TButton"
             and widget.cget("text") == "确认保存").invoke()
        self.drain()
        self.assertFalse(self.app.errors)
        self.assertEqual(len(self.app.undo_records), 2)
        for record in self.app.records.values():
            expected = "真正的原标题" if record.path == existing else record.path.stem
            self.assertEqual(read_audio(record.path).tags["title"], expected)

    def test_footer_and_save_visible_at_minimum_size(self):
        self.app.geometry("1120x780")
        self.app.update()
        save = self.app.controls[-1]
        relative_bottom = save.winfo_rooty() - self.app.winfo_rooty() + save.winfo_height()
        self.assertLess(relative_bottom, self.app.winfo_height())
        self.assertGreater(self.app.progress.winfo_height(), 0)
        self.assertLess(self.app.progress.winfo_y(), self.app.winfo_height())

    def test_chinese_text_commit_without_key_release(self):
        path = self.root / "中文.wav"
        make_wav(path)
        record = read_audio(path)
        self.app.records[str(path.resolve())] = record
        self.app._render_table()
        self.app.select_all()
        self.app.update()
        self.assertFalse(any(value.get() for value in self.app.checked.values()))
        # Committed IME text reaches the widget independently of normal key
        # releases. Exercise the widget edit, rather than setting the checkbox.
        entry = self.app.entries["artist"]
        entry.insert(0, "周杰伦")
        self.app.update()
        self.assertEqual(self.app.values["artist"].get(), "周杰伦")
        self.assertTrue(self.app.checked["artist"].get())
        self.assertFalse(self.app.checked["album"].get())
        self.app._selection_changed()
        self.assertEqual(entry.get(), "周杰伦")
        self.app.reset_editor()
        self.assertFalse(any(value.get() for value in self.app.checked.values()))

    @unittest.skipUnless(os.name == "nt", "Windows IME integration")
    def test_windows_ime_context_reconnects_without_replacing_live_context(self):
        ime = self.app.text_input
        self.assertTrue(ime._activated, "Windows text service did not activate")
        hwnd = self.app.entries["artist"].winfo_id()
        self.assertTrue(ime.imm.ImmAssociateContextEx(hwnd, None, 0))
        self.assertFalse(ime.imm.ImmGetContext(hwnd))
        self.assertTrue(ime.ensure_context(hwnd))
        context = ime.imm.ImmGetContext(hwnd)
        self.assertTrue(context)
        ime.imm.ImmReleaseContext(hwnd, context)
        self.assertTrue(ime.ensure_context(hwnd))
        current = ime.imm.ImmGetContext(hwnd)
        self.assertEqual(current, context)
        ime.imm.ImmReleaseContext(hwnd, current)


if __name__ == "__main__":
    unittest.main(verbosity=2)
