import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_metadata import (BACKUP_DIR, discover_files, plan_changes, read_audio, restore_audio,
                            save_audio, validate_changes)


def make_wav(path):
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(44100)
        stream.writeframes(b"\x00" * 44100 * 4)


def ffmpeg_executable():
    found = shutil.which("ffmpeg")
    if found:
        return found
    build_tools = Path(__file__).resolve().parents[1] / ".build-tools"
    candidates = list(build_tools.glob("imageio_ffmpeg/binaries/ffmpeg*.exe"))
    return str(candidates[0]) if candidates else None


class MetadataTests(unittest.TestCase):
    def setUp(self):
        artifacts = Path(__file__).resolve().parents[1] / ".test-artifacts"
        artifacts.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=artifacts)
        self.root = Path(self.temp.name)
        self.wav = self.root / "中文 空格.wav"
        make_wav(self.wav)

    def tearDown(self):
        self.temp.cleanup()

    def test_wav_roundtrip_preserves_audio_and_unchecked_tags(self):
        initial = self.wav.read_bytes()
        updated, backup = save_audio(read_audio(self.wav), {"title": "原曲名", "artist": "原歌手", "genre": "原曲风"}, "first")
        updated, second = save_audio(updated, {"artist": "新歌手 🎵", "album": "新专辑", "genre": ""}, "second")
        self.assertEqual(updated.tags["artist"], "新歌手 🎵")
        self.assertEqual(updated.tags["title"], "原曲名")
        self.assertEqual(updated.tags["genre"], "")
        self.assertEqual(updated.sample_rate, 44100)
        self.assertEqual(updated.bitrate, 1411200)
        with wave.open(str(self.wav), "rb") as stream:
            self.assertEqual(stream.readframes(44100), b"\x00" * 44100 * 4)
        restored = restore_audio(second)
        self.assertEqual(restored.tags["artist"], "原歌手")
        self.assertEqual(backup.backup.read_bytes(), initial)

    def test_external_change_blocks_write_and_restore(self):
        record = read_audio(self.wav)
        os.utime(self.wav, ns=(record.signature.mtime_ns, record.signature.mtime_ns + 1000000))
        with self.assertRaisesRegex(ValueError, "其他程序"):
            save_audio(record, {"artist": "x"}, "conflict")
        updated, backup = save_audio(read_audio(self.wav), {"artist": "x"}, "ok")
        os.utime(self.wav, ns=(updated.signature.mtime_ns, updated.signature.mtime_ns + 1000000))
        with self.assertRaisesRegex(ValueError, "不能自动撤销"):
            restore_audio(backup)

    def test_failed_stage_never_changes_original(self):
        initial = self.wav.read_bytes()
        with patch("audio_metadata._write_tags", side_effect=OSError("磁盘已满")):
            with self.assertRaises(OSError):
                save_audio(read_audio(self.wav), {"artist": "x"}, "fail")
        self.assertEqual(self.wav.read_bytes(), initial)
        self.assertFalse(list(self.root.glob(".audioedit-*")))

    def test_failed_backup_never_changes_original(self):
        initial = self.wav.read_bytes()
        real_copy = shutil.copy2
        def fail_backup(source, destination, *args, **kwargs):
            if BACKUP_DIR in str(destination):
                raise OSError("备份失败")
            return real_copy(source, destination, *args, **kwargs)
        with patch("audio_metadata.shutil.copy2", side_effect=fail_backup):
            with self.assertRaises(OSError):
                save_audio(read_audio(self.wav), {"artist": "x"}, "fail")
        self.assertEqual(self.wav.read_bytes(), initial)

    def test_discovery_deduplicates_and_excludes_backups(self):
        nested = self.root / "nested"
        nested.mkdir()
        shutil.copy2(self.wav, nested / "b.WAV")
        backup_dir = self.root / BACKUP_DIR / "old"
        backup_dir.mkdir(parents=True)
        shutil.copy2(self.wav, backup_dir / "backup.wav")
        self.assertEqual(len(list(discover_files([self.root, self.wav]))), 2)
        self.assertEqual(len(list(discover_files([self.root], recursive=False))), 1)

    def test_validation(self):
        for changes in ({}, {"date": "2026-02-30"}, {"date": "2026-13"}, {"tracknumber": "13/12"},
                        {"discnumber": "0"}, {"tracknumber": "99999"}, {"artist": "a\x00b"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_changes(changes)
        self.assertEqual(validate_changes({"date": "2024-02-29", "tracknumber": "2/12"})["date"], "2024-02-29")

    def test_empty_title_uses_filename_and_can_be_restored(self):
        path = self.root / "01.晴天.live.WAV"
        self.wav.rename(path)
        original_bytes = path.read_bytes()
        record = read_audio(path)
        targets = plan_changes([record], {})
        self.assertEqual(targets[0][1], {"title": "01.晴天.live"})
        self.assertEqual(path.read_bytes(), original_bytes, "Planning must not write to disk")
        updated, backup = save_audio(*targets[0], "auto-title")
        self.assertEqual(updated.tags["title"], "01.晴天.live")
        self.assertFalse(plan_changes([updated], {}))
        restore_audio(backup)
        self.assertEqual(path.read_bytes(), original_bytes)

    def test_auto_title_preserves_manual_edits_and_can_be_disabled(self):
        record = read_audio(self.wav)
        self.assertFalse(plan_changes([record], {}, fill_empty_titles=False))
        self.assertEqual(plan_changes([record], {"title": "手动标题"})[0][1], {"title": "手动标题"})
        self.assertFalse(plan_changes([record], {"title": ""}))
        record.tags["title"] = " \t "
        self.assertEqual(plan_changes([record], {})[0][1], {"title": "中文 空格"})
        record.tags["title"] = "已有标题"
        self.assertFalse(plan_changes([record], {}))
        self.assertEqual(plan_changes([record], {"artist": "歌手"})[0][1], {"artist": "歌手"})
        self.assertEqual(plan_changes([record], {"title": ""})[0][1], {"title": ""})

    @unittest.skipUnless(ffmpeg_executable(), "需要 FFmpeg 才能生成多格式测试音频")
    def test_real_audio_formats_roundtrip_and_decoded_audio_unchanged(self):
        ffmpeg = ffmpeg_executable()
        formats = [("mp3", "libmp3lame"), ("flac", "flac"), ("m4a", "aac"),
                   ("m4a", "alac"), ("ogg", "libvorbis"), ("opus", "libopus"),
                   ("aiff", "pcm_s16be"), ("wma", "wmav2")]
        for suffix, codec in formats:
            with self.subTest(codec=codec):
                path = self.root / f"音乐_{codec}.{suffix}"
                subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(self.wav), "-c:a", codec, str(path)], check=True, capture_output=True)
                decode = [ffmpeg, "-v", "error", "-i", str(path), "-f", "s16le", "-"]
                original_audio = subprocess.run(decode, check=True, capture_output=True).stdout
                original_bytes = path.read_bytes()
                record = read_audio(path)
                edits = {"title": "海边的歌", "artist": "歌手甲", "album": "夏日专辑", "albumartist": "群星",
                         "genre": "流行", "date": "2026-10-16", "tracknumber": "2/12", "discnumber": "1/2",
                         "composer": "作曲者乙", "comment": "中文备注 🎵"}
                updated, backup = save_audio(record, edits, codec)
                for key, value in edits.items():
                    self.assertEqual(updated.tags[key], value)
                after_audio = subprocess.run(decode, check=True, capture_output=True).stdout
                self.assertEqual(after_audio, original_audio)
                updated, _ = save_audio(updated, {"genre": "", "comment": ""}, codec + "clear")
                self.assertEqual(updated.tags["genre"], "")
                self.assertEqual(updated.tags["comment"], "")
                self.assertEqual(updated.tags["title"], "海边的歌")
                # Restore using a fresh signature because there was a second intentional write.
                backup.saved_signature = updated.signature
                restore_audio(backup)
                self.assertEqual(path.read_bytes(), original_bytes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
