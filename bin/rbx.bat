@echo off
REM rbx - RebrandX command line (Windows). No arguments opens the app.
setlocal
set "HERE=%~dp0"
python "%HERE%..\rebrandx\cli.py" %*
