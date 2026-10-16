@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo 请先安装 Python 3.10 或更高版本，并勾选 Add Python to PATH。
    pause
    exit /b 1
)
python -c "import bootstrap, mutagen" >nul 2>nul
if errorlevel 1 (
    echo 正在安装音频标签依赖...
    python -m pip install --target .vendor -r requirements.txt
    if errorlevel 1 (
        echo 安装失败，请检查网络后重试。
        pause
        exit /b 1
    )
)
python app.py
if errorlevel 1 pause
