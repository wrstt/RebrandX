@echo off
REM RebrandX - open the app window (Windows).
setlocal
set "HERE=%~dp0"
python "%HERE%..\rebrandx\app_win.py" %*
