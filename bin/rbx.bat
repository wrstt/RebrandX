@echo off
REM rbx - RebrandX command line. With no arguments it opens the app window.
REM
REM Finds Python via the py launcher first (it is what the python.org
REM installer registers and it works whether or not PATH was ticked), then
REM falls back to python.exe on PATH.
setlocal
set "HERE=%~dp0"

set "RBX_PY="
py -3 -c "" >nul 2>&1 && set "RBX_PY=py -3"
if not defined RBX_PY (
    python -c "" >nul 2>&1 && set "RBX_PY=python"
)
if not defined RBX_PY (
    echo RebrandX needs Python 3.8 or newer.>&2
    echo Install it from https://www.python.org/downloads/ and tick>&2
    echo "Add Python to PATH" during setup.>&2
    exit /b 9009
)

%RBX_PY% "%HERE%..\rebrandx\cli.py" %*
exit /b %ERRORLEVEL%
