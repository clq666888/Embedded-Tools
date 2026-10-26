@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe make_icon.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --name "UART Tool" --icon "%~dp0assets\uart.ico" --workpath build-release --distpath dist-release --specpath build-release main.py
if errorlevel 1 goto failed
copy /y "dist-release\UART Tool.exe" "UART串口助手.exe" >nul
if errorlevel 1 goto failed
if not exist dist mkdir dist
copy /y "dist-release\UART Tool.exe" "dist\UART Tool.exe" >nul
echo.
echo Build complete: UART串口助手.exe
pause
exit /b 0
:failed
echo.
echo Build failed. Please check Python and network access.
pause
exit /b 1
