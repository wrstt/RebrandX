@echo off
REM RebrandX - open the app window (Windows).
REM
REM Uses pythonw where it can, so double-clicking this file does not leave a
REM console window sitting behind the app. Nothing else is needed: the window
REM is built on tkinter, which ships with Python.
setlocal
set "HERE=%~dp0"

set "RBX_PY="
pyw -3 -c "" >nul 2>&1 && set "RBX_PY=pyw -3"
if not defined RBX_PY (
    pythonw -c "" >nul 2>&1 && set "RBX_PY=pythonw"
)
if not defined RBX_PY (
    py -3 -c "" >nul 2>&1 && set "RBX_PY=py -3"
)
if not defined RBX_PY (
    python -c "" >nul 2>&1 && set "RBX_PY=python"
)
if not defined RBX_PY (
    echo RebrandX needs Python 3.8 or newer.>&2
    echo Install it from https://www.python.org/downloads/ and tick>&2
    echo "Add Python to PATH" during setup.>&2
    exit /b 9009
)

%RBX_PY% "%HERE%..\rebrandx\app_tk.py" %*
exit /b %ERRORLEVEL%
