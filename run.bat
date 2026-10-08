@echo off
REM ---------------------------------------------------------------------------
REM  AP Physics C: Mechanics question bank - start the local server
REM ---------------------------------------------------------------------------
setlocal
set PY=C:\Users\hxue7\.workbuddy\binaries\python\envs\default\Scripts\python.exe
if not exist "%PY%" set PY=python
pushd "%~dp0"
"%PY%" -m uvicorn server.main:app --host 127.0.0.1 --port 8765 --reload
popd
endlocal
