@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 doit etre installe pour lancer le pilote.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto :erreur
)
".venv\Scripts\python.exe" -c "import flask, waitress" >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :erreur
)
set HUB_PILOTE_OUVRIR=1
".venv\Scripts\python.exe" nuage_pilote.py
if errorlevel 1 goto :erreur
exit /b 0
:erreur
echo Impossible de lancer le pilote. Lisez le message ci-dessus.
pause
exit /b 1
