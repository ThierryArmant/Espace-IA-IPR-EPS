@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 doit etre installe pour lancer le Hub.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto :erreur
)
".venv\Scripts\python.exe" -c "import flask, waitress, cryptography" >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :erreur
)
".venv\Scripts\python.exe" lancer_hub_local.py
if errorlevel 1 goto :erreur
exit /b 0
:erreur
echo Impossible de lancer le Hub. Lisez le message ci-dessus.
pause
exit /b 1
