@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe make_icon.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name "固件文件检查工具" --icon "%~dp0assets\firmware.ico" --add-data "%~dp0assets\firmware.ico;assets" --distpath "." --workpath "build" --specpath "build" main.py
if errorlevel 1 goto failed
echo 打包完成：固件文件检查工具.exe
exit /b 0
:failed
echo 打包失败。
exit /b 1
