"""Audio metadata adapters and recoverable, staged file operations."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import bootstrap  # noqa: F401
import mutagen
from mutagen.aiff import AIFF
from mutagen.asf import ASF
from mutagen.flac import FLAC
from mutagen.id3 import COMM, TALB, TCOM, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggflac import OggFLAC
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

EXTENSIONS = {".mp3", ".flac", ".m4a", ".m4b", ".mp4", ".ogg", ".oga", ".opus", ".wav", ".aif", ".aiff", ".wma"}
FIELDS = {
    "title": "标题", "artist": "歌手", "album": "专辑", "albumartist": "专辑歌手",
    "genre": "曲风", "date": "发行日期", "tracknumber": "音轨编号",
    "discnumber": "碟片编号", "composer": "作曲者", "comment": "备注",
}
ID3_FRAMES = {
    "title": TIT2, "artist": TPE1, "album": TALB, "albumartist": TPE2,
    "genre": TCON, "date": TDRC, "tracknumber": TRCK, "discnumber": TPOS,
    "composer": TCOM,
}
MP4_KEYS = {
    "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "albumartist": "aART",
    "genre": "\xa9gen", "date": "\xa9day", "tracknumber": "trkn", "discnumber": "disk",
    "composer": "\xa9wrt", "comment": "\xa9cmt",
}
ASF_KEYS = {
    "title": "Title", "artist": "Author", "album": "WM/AlbumTitle",
    "albumartist": "WM/AlbumArtist", "genre": "WM/Genre", "date": "WM/Year",
    "tracknumber": "WM/TrackNumber", "discnumber": "WM/PartOfSet",
    "composer": "WM/Composer", "comment": "Description",
}
SUPPORTED_TYPES = (MP3, FLAC, MP4, OggVorbis, OggOpus, OggFLAC, WAVE, AIFF, ASF)
BACKUP_DIR = ".audio-tag-backups"


@dataclass(frozen=True)
class Signature:
    size: int
    mtime_ns: int

    @classmethod
    def of(cls, path: Path) -> Signature:
        stat = path.stat()
        return cls(stat.st_size, stat.st_mtime_ns)


@dataclass
class AudioRecord:
    path: Path
    tags: dict[str, str]
    format: str
    codec: str
    duration: float
    bitrate: int
    sample_rate: int
    channels: int
    bits_per_sample: int
    signature: Signature
    bitrate_estimated: bool = False


@dataclass
class BackupRecord:
    original: Path
    backup: Path
    saved_signature: Signature


def _load(path: Path):
    audio = mutagen.File(path)
    if audio is None or not isinstance(audio, SUPPORTED_TYPES):
        raise ValueError("不支持此音频编码或文件格式")
    return audio


def _tags(audio) -> dict[str, str]:
    result = dict.fromkeys(FIELDS, "")
    tags = audio.tags
    if tags is None:
        return result
    for key in FIELDS:
        if isinstance(audio, (MP3, WAVE, AIFF)):
            if key == "comment":
                frames = tags.getall("COMM")
                values = [str(v) for f in frames for v in f.text]
            else:
                values = [str(v) for f in tags.getall(ID3_FRAMES[key].__name__) for v in f.text]
        elif isinstance(audio, MP4):
            values = tags.get(MP4_KEYS[key], [])
            if key in ("tracknumber", "discnumber"):
                values = [f"{n}/{total}" if total else str(n) for n, total in values]
        elif isinstance(audio, ASF):
            values = [str(v) for v in tags.get(ASF_KEYS[key], [])]
        else:
            values = tags.get(key, [])
        result[key] = "; ".join(str(v) for v in values)
    return result


def read_audio(path: str | Path) -> AudioRecord:
    path = Path(path).resolve()
    before = Signature.of(path)
    audio = _load(path)
    info = audio.info
    names = {MP3: "MP3", FLAC: "FLAC", MP4: "M4A / MP4", OggVorbis: "OGG",
             OggOpus: "OPUS", OggFLAC: "OGG FLAC", WAVE: "WAV", AIFF: "AIFF", ASF: "WMA"}
    name = next(label for cls, label in names.items() if isinstance(audio, cls))
    duration = float(getattr(info, "length", 0) or 0)
    bitrate = int(getattr(info, "bitrate", 0) or 0)
    estimated = not bitrate and duration > 0
    if estimated:
        bitrate = round(before.size * 8 / duration)
    codec = str(getattr(info, "codec_description", "") or getattr(info, "codec", "") or name)
    if isinstance(audio, OggOpus):
        codec = "Opus"
    tags = _tags(audio)
    if Signature.of(path) != before:
        raise ValueError("读取期间文件发生变化，请重新添加")
    return AudioRecord(path, tags, name, codec, duration, bitrate,
                       int(getattr(info, "sample_rate", 0) or (48000 if isinstance(audio, OggOpus) else 0)),
                       int(getattr(info, "channels", 0) or 0),
                       int(getattr(info, "bits_per_sample", 0) or 0), before, estimated)


def validate_changes(changes: dict[str, str]) -> dict[str, str]:
    if not changes:
        raise ValueError("请先勾选要修改的字段")
    normalized = {}
    for key, value in changes.items():
        if key not in FIELDS:
            raise ValueError(f"未知字段：{key}")
        value = value.strip()
        if "\x00" in value:
            raise ValueError(f"{FIELDS[key]}不能包含空字符")
        if key in ("tracknumber", "discnumber") and value:
            if not re.fullmatch(r"[1-9]\d{0,4}(?:/[1-9]\d{0,4})?", value):
                raise ValueError(f"{FIELDS[key]}请使用 1 或 1/12 格式")
            numbers = list(map(int, value.split("/")))
            if max(numbers) > 65535 or (len(numbers) == 2 and numbers[0] > numbers[1]):
                raise ValueError(f"{FIELDS[key]}超出范围，或编号大于总数")
        if key == "date" and value:
            if not re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", value):
                raise ValueError("发行日期请使用 YYYY、YYYY-MM 或 YYYY-MM-DD")
            try:
                datetime.strptime(value, {4: "%Y", 7: "%Y-%m", 10: "%Y-%m-%d"}[len(value)])
            except ValueError:
                raise ValueError("发行日期无效") from None
        normalized[key] = value
    return normalized


def plan_changes(records: Iterable[AudioRecord], changes: dict[str, str],
                 fill_empty_titles: bool = True) -> list[tuple[AudioRecord, dict[str, str]]]:
    """Plan per-file edits without hiding missing tags or writing during scans."""
    normalized = validate_changes(changes) if changes else {}
    targets = []
    for record in records:
        edits = {key: value for key, value in normalized.items() if record.tags[key] != value}
        # Explicit title edits (including an intentional clear) take precedence.
        if fill_empty_titles and "title" not in normalized and not record.tags["title"].strip():
            edits["title"] = record.path.stem.strip()
        if edits:
            targets.append((record, edits))
    return targets


def _write_tags(audio, changes: dict[str, str]):
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    for key, value in changes.items():
        if isinstance(audio, (MP3, WAVE, AIFF)):
            if key == "comment":
                tags.delall("COMM")
                if value:
                    tags.add(COMM(encoding=3, lang="eng", desc="", text=[value]))
            else:
                cls = ID3_FRAMES[key]
                tags.delall(cls.__name__)
                if value:
                    tags.add(cls(encoding=3, text=[value]))
        else:
            tag_key = MP4_KEYS[key] if isinstance(audio, MP4) else ASF_KEYS[key] if isinstance(audio, ASF) else key
            # Old numeric iTunes genres otherwise become visible again after clearing.
            if isinstance(audio, MP4) and key == "genre":
                if "gnre" in tags:
                    del tags["gnre"]
            if not value:
                if tag_key in tags:
                    del tags[tag_key]
            elif isinstance(audio, MP4) and key in ("tracknumber", "discnumber"):
                parts = list(map(int, value.split("/")))
                tags[tag_key] = [(parts[0], parts[1] if len(parts) == 2 else 0)]
            else:
                tags[tag_key] = [value]
    audio.save()


def _staging_file(path: Path) -> Path:
    handle, name = tempfile.mkstemp(prefix=".audioedit-", suffix=path.suffix, dir=path.parent)
    os.close(handle)
    return Path(name)


def save_audio(record: AudioRecord, changes: dict[str, str], batch_id: str) -> tuple[AudioRecord, BackupRecord]:
    changes = validate_changes(changes)
    path = record.path
    if Signature.of(path) != record.signature:
        raise ValueError("文件已被其他程序修改，请刷新后重试")
    stage = _staging_file(path)
    try:
        shutil.copy2(path, stage)
        _write_tags(_load(stage), changes)
        verified = read_audio(stage)
        for key, value in changes.items():
            if verified.tags[key] != value:
                raise ValueError(f"{FIELDS[key]}写入校验未通过，原文件未修改")
        folder = path.parent / BACKUP_DIR / batch_id
        folder.mkdir(parents=True, exist_ok=True)
        backup = folder / f"{uuid.uuid4().hex[:12]}_{path.name}"
        if Signature.of(path) != record.signature:
            raise ValueError("保存期间文件发生变化，已停止覆盖")
        shutil.copy2(path, backup)
        # Keep a readable restoration map even after the application exits.
        manifest = backup.with_name(backup.name + ".json")
        manifest.write_text(json.dumps({"original": str(path), "backup": str(backup),
                                       "created": datetime.now().isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")
        if Signature.of(path) != record.signature:
            raise ValueError("备份期间文件发生变化，已停止覆盖")
        os.replace(stage, path)
        updated = read_audio(path)
        return updated, BackupRecord(path, backup, updated.signature)
    finally:
        stage.unlink(missing_ok=True)


def restore_audio(backup: BackupRecord) -> AudioRecord:
    if Signature.of(backup.original) != backup.saved_signature:
        raise ValueError("保存后文件又发生了变化，不能自动撤销；可从备份目录手动恢复")
    stage = _staging_file(backup.original)
    try:
        shutil.copy2(backup.backup, stage)
        read_audio(stage)
        if Signature.of(backup.original) != backup.saved_signature:
            raise ValueError("恢复期间文件发生变化，已停止覆盖")
        os.replace(stage, backup.original)
        return read_audio(backup.original)
    finally:
        stage.unlink(missing_ok=True)


def discover_files(paths: Iterable[str | Path], recursive: bool = True, on_error=None):
    """Stream paths, skip backups/symlinks, and deduplicate across inputs."""
    seen = set()
    for input_path in paths:
        path = Path(input_path)
        if path.is_dir():
            def report(error):
                if on_error:
                    on_error(error)
            for root, dirs, files in os.walk(path, onerror=report, followlinks=False):
                dirs[:] = sorted(d for d in dirs if d != BACKUP_DIR and not Path(root, d).is_symlink()) if recursive else []
                for name in sorted(files):
                    file = Path(root, name)
                    if file.suffix.lower() not in EXTENSIONS or file.is_symlink() or file.name.startswith(".audioedit-"):
                        continue
                    resolved = file.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        yield resolved
        elif path.suffix.lower() in EXTENSIONS:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield resolved


def duration_text(seconds: float) -> str:
    seconds = max(0, round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def size_text(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB" if size >= 1024 * 1024 else f"{size / 1024:.1f} KB"
