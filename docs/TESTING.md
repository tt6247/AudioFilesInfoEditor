# 测试与排障

## 执行环境

元数据测试使用 `unittest`，主要通过临时 WAV 文件验证读写。桌面测试会创建真实 Tk 窗口，需要可用桌面；Windows 输入法测试还需要正常访问系统文本服务。不要把受限环境无法创建输入法上下文直接判定为应用逻辑回归。

先按[开发入门](DEVELOPMENT.md)安装运行依赖。为运行真实编码测试，可将开发用 FFmpeg 包放在项目内：

```powershell
python -m pip install --target .build-tools imageio-ffmpeg==0.6.0
python -m unittest discover -s tests -v
```

测试先从 `PATH` 查找 `ffmpeg`，再从 `.build-tools/imageio_ffmpeg/binaries/ffmpeg*.exe` 查找。没有找到时，多编码测试会标记为跳过；不能将带有该跳过的结果描述为完成了全部多格式验证。

只检查元数据部分：

```powershell
python -m unittest discover -s tests -p test_metadata.py -v
```

测试在 `.test-artifacts` 下创建临时子目录，正常结束时清理。备份和损坏样本也只位于测试自己的目录，不应将个人音乐库作为自动测试输入。

## 现有自动检查

v1.1 对应 14 项测试：元数据 9 项、桌面流程 5 项。以后新增测试时，以实际测试输出为准。

| 测试 | 验证内容 |
| --- | --- |
| `test_wav_roundtrip_preserves_audio_and_unchecked_tags` | 中文标签、清空字段、保留未选标签、PCM 内容与备份 |
| `test_external_change_blocks_write_and_restore` | 保存或撤销前发现外部修改时拒绝覆盖 |
| `test_failed_stage_never_changes_original` | 模拟写副本失败，原文件不变，临时文件清理 |
| `test_failed_backup_never_changes_original` | 模拟备份失败，原文件不变 |
| `test_discovery_deduplicates_and_excludes_backups` | 递归扫描、去重、排除备份和非递归模式 |
| `test_validation` | 日期、编号、空字符及空修改输入校验 |
| `test_empty_title_uses_filename_and_can_be_restored` | 多点号文件名补标题、计划阶段不写盘、备份恢复 |
| `test_auto_title_preserves_manual_edits_and_can_be_disabled` | 空白标题、已有标题、手动输入/清空优先和关闭补填 |
| `test_real_audio_formats_roundtrip_and_decoded_audio_unchanged` | FFmpeg 生成八类编码样本，标签往返与解码音频一致 |
| `test_batch_scan_filter_preview_save_undo` | 后台扫描、损坏文件、搜索、多选、预览、保存和撤销 |
| `test_auto_title_preview_and_batch_save_without_checked_fields` | 按每首文件名补填，保留已有标题，预览两首独立改动 |
| `test_footer_and_save_visible_at_minimum_size` | 最小窗口下保存按钮与底栏可见 |
| `test_chinese_text_commit_without_key_release` | 没有普通按键释放时，文字编辑仍标记待保存；切换选择和重置 |
| `test_windows_ime_context_reconnects_without_replacing_live_context` | TSF 激活、缺失 IMM 上下文重连、保留已连接上下文 |

多编码样本包含 MP3、FLAC、AAC、ALAC、Ogg Vorbis、Opus、AIFF PCM 和 WMA。WAV 另有独立测试；Ogg FLAC 虽在支持类型中，目前未在该多编码测试中生成样本。

音频内容对比通过 FFmpeg 解码到原始 PCM 后比较。文件整体字节因标签和容器结构更新可能变化，因此不能用“保存后文件哈希必须相同”代替音频内容检查。恢复原备份的测试则会比较完整文件字节。

## 发布前的桌面验收

以下场景需要在打包后的 EXE 中人工检查，不能由当前自动检查完全替代：

1. 在文件管理器中双击启动，无需 Python 或管理员权限，程序窗口正常显示。
2. 使用系统中文输入法或“中文输入”按钮，在歌手/专辑框输入拼音、看到候选字、选字上屏；再测试粘贴和 Shift 切换。
3. 添加包含不同格式与中文文件名的临时音乐目录，检查筛选、多选、横向滚动和音频参数。
4. 混合选择空标题和已有标题的音档，确认预览只补缺失标题，并去掉最后的扩展名。
5. 验证手动标题优先、主动清空、关闭自动补填、未勾选字段保留。
6. 确认保存前有原值/新值预览，保存后有完整备份；撤销后音档恢复。
7. 测试高 DPI、最小窗口、右侧编辑区滚动及任务停止。停止应发生在当前文件处理完成后。

仅使用可丢弃的测试音档做验收。记录系统、Python/Tk 或 EXE 版本、复现步骤和实际结果，不要仅写“测试通过”。

## 常见问题

| 现象 | 检查方法 |
| --- | --- |
| 缺少 `mutagen` | 在项目根目录重新执行运行依赖安装命令；检查 `.vendor` 是否与当前 Python 对应 |
| 无法创建 Tk 窗口 | 确认 Python 安装包含 Tcl/Tk，并在有桌面的会话中运行 |
| 无法切中文或候选字不出现 | 在普通桌面重新启动；聚焦输入框后点击“中文输入”；确认系统已安装中文输入法 |
| 多编码测试被跳过 | 检查 FFmpeg 的 `PATH` 或项目内备用查找位置 |
| 文件已被其他程序修改 | 先刷新文件信息，再重新预览；不要关闭签名检查绕过冲突 |
| 无法备份或替换 | 检查原目录权限、剩余空间、只读属性，以及是否被其他程序占用；查看失败详情 |
| 撤销时提示保存后又发生变化 | 自动撤销按设计拒绝覆盖；根据备份 JSON 路径人工核对后恢复 |
| 标签在某播放器中未变化 | 先重新读取文件确认保存结果，再检查播放器缓存与对应标签格式支持 |

排查问题时可记录相关文件名、格式、预期值和错误文本。提交问题前应移除不必要的个人目录信息与音乐文件内容。
