@echo off
rem Research_Area_Viwer: PC dashboard launcher (Windows)
rem Double-click this file. First run creates a Python environment (.venv).
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set "PY=python"
where py >nul 2>nul && set "PY=py -3"

if not exist ".venv\Scripts\python.exe" (
  echo [setup] Creating Python environment. This takes a few minutes only the first time...
  %PY% -m venv .venv || goto :nopython
  ".venv\Scripts\python.exe" -m pip install -q -r backend\requirements.txt || goto :fail
)

if "%OPENALEX_API_KEY%"=="" (
  echo OpenAlex API key is not set. It will be saved to your Windows user environment.
  set /p "OPENALEX_API_KEY=OpenAlex API key: "
  if "!OPENALEX_API_KEY!"=="" goto :nokey
  setx OPENALEX_API_KEY "!OPENALEX_API_KEY!" >nul
)

cd backend
echo Starting dashboard... (close this window or press Ctrl+C to stop)
"..\.venv\Scripts\python.exe" -m openalex_trend serve --open
goto :end

:nopython
echo Python 3.11 or later was not found. Install it from https://www.python.org/downloads/
echo (check "Add python.exe to PATH" during installation), then run this file again.
goto :end

:nokey
echo No API key was entered. Get a free key at https://openalex.org/settings/api
goto :end

:fail
echo Failed to install packages. Check your internet connection and run this file again.
echo To retry from scratch, delete the .venv folder.

:end
pause
