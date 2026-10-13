@echo off
rem TriageSim DEMO: invented data, safe to show. Double-click to start.
title TriageSim (demo)
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo First run: installing uv, which sets up Python and the app. This takes a few minutes.
    powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
)
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

uv run triagesim ui --demo
if errorlevel 1 pause
