@echo off
rem TriageSim: double-click this file to start.
title TriageSim
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo First run: installing uv, which sets up Python and the app. This takes a few minutes.
    powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
)
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

uv run triagesim ui
if errorlevel 1 pause
