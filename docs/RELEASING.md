# 打包与发布

## 当前版本与发布范围

当前界面版本为 v1.1，Git 标签为 `v1.1.0`，Windows 文件名为 `AudioFilesInfoEditor-v1.1.exe`。项目目前没有集中版本配置或自动发布流程，升级版本时需要同步检查 `app.py` 窗口标题、README、构建文件名、版本记录和 Git 标签。

纯文档更新直接提交到 `main`，不需要重打包或移动已发布标签。程序代码更新则应完成验证、生成对应 EXE，并使用新的版本标签发布。

## 安装构建工具

在 Windows 项目根目录执行：

```powershell
python -m pip install --target .vendor -r requirements.txt
python -m pip install --target .build-tools pyinstaller==6.22.3 imageio-ffmpeg==0.6.0
python -m unittest discover -s tests -v
```

PyInstaller 版本取自 v1.1 已使用的构建环境。升级构建工具时应重新验证生成的程序。FFmpeg 包用于测试，不是应用运行依赖，也不应作为应用数据一起打包。

## 构建 Windows EXE

下面以 v1.1 文件名演示；发布新版本前先替换对应版本号。设置 `PYTHONPATH` 是为了让当前 Python 找到项目内的构建工具，结束后恢复原值：

```powershell
$taskPreviousPythonPath = $env:PYTHONPATH
try {
    $taskBuildPaths = @("$PWD\.build-tools", "$PWD\.vendor")
    if ($taskPreviousPythonPath) {
        $taskBuildPaths += $taskPreviousPythonPath
    }
    $env:PYTHONPATH = $taskBuildPaths -join [IO.Path]::PathSeparator
    python -m PyInstaller --noconfirm --clean --onefile --windowed --name AudioFilesInfoEditor-v1.1 --paths .vendor app.py
    if ($LASTEXITCODE -ne 0) {
        throw "Windows 程序打包失败"
    }
}
finally {
    $env:PYTHONPATH = $taskPreviousPythonPath
}
```

输出位于 `dist/AudioFilesInfoEditor-v1.1.exe`；`build` 和 `.spec` 是构建产物，不提交到源码仓库。打包后按[桌面验收步骤](TESTING.md)检查 EXE，尤其是中文输入候选字、自动补填、保存与撤销。单纯成功生成 EXE 不等于完成桌面验收。

记录发布文件的 SHA-256：

```powershell
Get-FileHash -LiteralPath dist\AudioFilesInfoEditor-v1.1.exe -Algorithm SHA256
```

源码分支、标签和实际生成 EXE 的提交需要对应。不要将旧 EXE 换个文件名后当作新版本发布。

## 同步源码到 GitHub

现有远程仓库为 `https://github.com/tt6247/AudioFilesInfoEditor.git`，主分支为 `main`。提交前检查：

```powershell
git fetch origin
git status --short --branch
git diff --check
git diff --stat
```

如果远端有新提交，先审阅并整合后再推送。用明确路径选择本次修改，检查暂存差异后提交；例如只更新文档时：

```powershell
git add -- README.md CHANGELOG.md docs
git diff --cached --check
git diff --cached --stat
git commit -m "docs: organize developer documentation"
git push origin main
```

缓存、临时音档和完整原始备份应保持在忽略范围内。不要在仓库、发布说明或脚本中写入 GitHub 密码或令牌；使用本机 Git 的登录机制完成推送。

## 创建程序发布版本

完成代码提交、自动检查和 EXE 验收后，为对应提交创建一个尚未使用的版本标签，再推送标签。以下使用变量表示下一版本，请先将值替换为实际版本：

```powershell
$taskReleaseTag = "v1.2.0"
git tag -a $taskReleaseTag -m "AudioFilesInfoEditor $taskReleaseTag"
git push origin $taskReleaseTag
```

`v1.2.0` 仅为流程示例，不表示该版本已经实现或发布。当前 `v1.1.0` 已存在，不要覆盖或移动它。

进入 [GitHub Releases](https://github.com/tt6247/AudioFilesInfoEditor/releases)，选择新推送的标签创建发布，写明本次改动、使用方式及实际验证结果。上传对应版本的 EXE、README、LICENSE 和 THIRD_PARTY_NOTICES；源码由 GitHub 按标签提供下载。开发文档也随标签源码包含在内。

发布完成后确认：仓库目标分支已包含本地提交，标签指向构建所用提交，EXE 名称及大小正确，下载文件的 SHA-256 与本地一致，README 的下载入口可达。README 等附件属于当次发布的快照；以后只更新 `main` 的文档不会自动更新旧版附件。

第三方依赖与分发说明以 [LICENSE](../LICENSE) 和[第三方声明](../THIRD_PARTY_NOTICES.md) 为准。调整打包依赖时同步核对这两份材料。
