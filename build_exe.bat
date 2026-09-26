@echo off
title Build got_psarc_tool.exe
echo ===================================================
echo Building Ghost of Tsushima PSARC Tool Standalone EXE
echo ===================================================

pip install -r requirements.txt pyinstaller
pyinstaller --onefile --name "got_psarc_tool" got_psarc_tool.py

echo.
if exist "dist\got_psarc_tool.exe" (
    copy /Y "dist\got_psarc_tool.exe" "got_psarc_tool.exe"
    echo [SUCCESS] got_psarc_tool.exe created successfully!
) else (
    echo [ERROR] Build failed! Check the log above.
)

pause
