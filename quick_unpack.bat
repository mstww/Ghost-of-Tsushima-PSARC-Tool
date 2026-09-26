@echo off
title Quick PSARC Unpacker - Ghost of Tsushima
echo ========================================================
echo Quick PSARC Unpacker - Ghost of Tsushima DIRECTOR'S CUT
echo ========================================================
echo.

if "%~1"=="" (
    echo Drag and drop a .psarc file onto this batch script to extract it!
    echo.
    set /p "TARGET=Or enter the path to a .psarc file: "
) else (
    set "TARGET=%~1"
)

if "%TARGET%"=="" goto end

if exist "%~dp0got_psarc_tool.exe" (
    "%~dp0got_psarc_tool.exe" unpack "%TARGET%"
) else (
    python "%~dp0got_psarc_tool.py" unpack "%TARGET%"
)

:end
echo.
pause
