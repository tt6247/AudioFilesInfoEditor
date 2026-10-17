# 开发入门

## 开发环境

项目使用 Python、Tkinter/ttk 和 Mutagen，面向 Windows 桌面。Python 要求为 3.10 或更新版本，安装时需要包含 Tcl/Tk 和 pip。运行程序不需要 FFmpeg；FFmpeg 仅用于生成多编码测试音档和验证音频内容。

v1.1 初始开发与打包使用 Python 3.10.11、Tk 8.6.12、Mutagen 1.48.1 和 PyInstaller 6.22.3。这是已使用的环境记录，不是对其他组合的兼容性保证。实际运行依赖范围以 [requirements.txt](../requirements.txt) 为准。

在普通 Windows 桌面的 PowerShell 中执行：

```powershell
git clone https://github.com/tt6247/AudioFilesInfoEditor.git
Set-Location AudioFilesInfoEditor
python --version
python -m pip install --target .vendor -r requirements.txt
python app.py
```

也可以双击 [start.bat](../start.bat)。它会检查 Python 和 Mutagen，必要时将运行依赖安装到项目内的 `.vendor`，然后启动程序。首次安装依赖需要联网；依赖就绪后，音档读取和编辑均在本机完成。

`bootstrap.py` 会把 `.vendor` 放到 Python 模块搜索路径最前面。如果同时使用虚拟环境，需留意 `.vendor` 内的同名库仍会优先加载，避免误判正在测试的依赖版本。

检查实际环境：

```powershell
python -c "import sys, bootstrap, mutagen, tkinter as tk; root=tk.Tk(); print(sys.version); print('Mutagen', mutagen.version_string); print('Tk', root.tk.call('info', 'patchlevel')); root.destroy()"
```

## 源码目录

| 路径 | 职责 |
| --- | --- |
| `app.py` | `AudioEditor` 主窗口、选择与筛选、修改预览、后台任务和状态反馈 |
| `audio_metadata.py` | 音档识别、统一标签、输入校验、逐文件修改计划、保存和恢复 |
| `windows_text_input.py` | 当前界面线程的 Windows 中文输入法连接及资源释放 |
| `bootstrap.py` | 加载项目内的运行依赖 |
| `requirements.txt` | 运行依赖范围 |
| `start.bat` | Windows 源码启动入口 |
| `tests/test_metadata.py` | 元数据、备份、冲突保护、多编码音频内容验证 |
| `tests/test_app.py` | 真实 Tk 事件循环、批量预览保存、自动补填和输入法连接测试 |
| `docs/` | 开发与维护文档 |

`.vendor`、`.build-tools`、`.test-artifacts`、`build`、`dist`、`.package`、生成的 `.spec` 和本地构建日志均被 Git 忽略。测试音档及运行中的完整备份也不属于源码发布内容。

## 调试入口

界面问题从 `AudioEditor` 中对应操作开始追踪：

| 场景 | 主要入口 |
| --- | --- |
| 添加文件或扫描目录 | `_scan()` → `discover_files()` → `read_audio()` |
| 字段未被标记为待修改 | `_field_changed()`、`_loading_values` |
| 空标题建议或保存结果 | `_render_table()`、`_selection_changed()`、`plan_changes()` |
| 预览与写入不一致 | `preview_save()` → `_save_targets()` → `save_audio()` |
| 窗口卡顿或进度异常 | `_start()`、`_poll()`、后台任务的队列事件 |
| 中文候选字不出现 | `_text_focus()`、`enable_chinese_input()`、`WindowsTextInput` |
| 撤销失败 | `undo()`、`restore_audio()`、文件签名 |

调试时从终端运行 `python app.py`，可看到 Python 异常。正式 EXE 使用 `--windowed`，不显示终端窗口。失败的单个音档通过界面的“查看失败详情”展示原因。

## 修改功能时的约定

Tk 控件和 Tk 变量由界面线程操作。文件扫描、标签写入和恢复在工作线程执行，通过队列汇报结果。新增耗时操作应沿用该方式。

新增标签字段时，需要同步修改 `FIELDS`、`ID3_FRAMES`、`MP4_KEYS` 和 `ASF_KEYS`，检查 Vorbis Comment 分支，并补充不同标签家族的读写测试。不能只添加一个界面输入框。

新增格式时，需要更新扩展名集合、`SUPPORTED_TYPES`、格式名称识别以及标签读写适配，并用实际编码样本验证。不能只依据文件扩展名承诺支持。

调整自动补填时，应先修改 `plan_changes()` 的规则，再检查列表建议、输入框展示和预览是否一致。`AudioRecord.tags` 应始终保留从文件读取的实际值；扫描阶段不写文件。

中文输入框通过文本变量变化识别实际编辑，避免依赖普通按键释放事件。修改输入逻辑时，应同时验证拼音选字、粘贴、切换选中音档和“重置待修改内容”。

提交前查看差异并完成与改动相关的验证：

```powershell
git diff --check
git diff --stat
git status --short
```

测试步骤见[测试与排障](TESTING.md)，发布步骤见[打包与发布](RELEASING.md)。
