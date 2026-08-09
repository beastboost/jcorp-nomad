@echo off
rem nomad-setup launcher.
rem   Double-clicking works. The SD card step additionally needs an
rem   Administrator prompt, because partitioning a disk requires elevation.
setlocal EnableExtensions

set "PYTHONPATH=%~dp0;%PYTHONPATH%"
set "PYEXE="

rem Actually execute each candidate instead of trusting PATH. On Windows a bare
rem "python" is very often the Microsoft Store stub: "where python" finds it
rem happily, but running it just opens the Store and exits. The py launcher is
rem the dependable one, so try it first.
call :probe py -3
if not defined PYEXE call :probe python
if not defined PYEXE call :probe python3
if not defined PYEXE goto :no_python

%PYEXE% -m nomad_setup %*
set "RC=%ERRORLEVEL%"
goto :finish

:no_python
echo.
echo   Could not find a working Python 3.
echo.
echo   Install it from https://www.python.org/downloads/ and tick
echo   "Add python.exe to PATH" in the installer, then run this again.
echo.
set "RC=1"
goto :finish

:probe
%* -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYEXE=%*"
goto :eof

:finish
rem If this was double-clicked from Explorer the console closes the instant the
rem script ends, taking any error message with it. Detect that and hold the
rem window open. Run from a prompt, it returns immediately as normal.
echo %cmdcmdline% | find /i "%~nx0" >nul
if not errorlevel 1 (
  echo.
  echo   [nomad-setup exited with code %RC%]
  echo.
  pause
)
exit /b %RC%
