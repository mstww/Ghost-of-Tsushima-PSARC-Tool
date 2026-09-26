@echo off
title Quick PSARC Repacker - Ghost of Tsushima
echo ========================================================
echo Quick PSARC Repacker - Ghost of Tsushima DIRECTOR'S CUT
echo ========================================================
echo.

if "%~1"=="" (
    echo Drag and drop an extracted folder onto this batch script to repack it!
    echo.
    set /p "TARGET=Or enter the path to the folder: "
) else (
    set "TARGET=%~1"
)

if "%TARGET%"=="" goto end

if exist "%~dp0got_psarc_tool.exe" (
    "%~dp0got_psarc_tool.exe" pack "%TARGET%"
) else (
    python "%~dp0got_psarc_tool.py" pack "%TARGET%"
)

:end
echo.
pause
