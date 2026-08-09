@echo off
rem nomad-setup launcher.
rem
rem   Re-launches itself elevated, because the SD card step partitions a disk
rem   and that needs Administrator rights. Set NOMAD_SKIP_ELEVATE=1 to run
rem   without it - flashing firmware does not need elevation, only the card
rem   step does.
setlocal EnableExtensions

rem Work from the script's own folder so an elevated re-launch (which starts in
rem system32) still finds everything.
cd /d "%~dp0"
set "PYTHONPATH=%~dp0;%PYTHONPATH%"

rem ---------------------------------------------------------- elevation ----
if /i "%NOMAD_SKIP_ELEVATE%"=="1" goto :run

rem fltmc only succeeds when elevated, and exists on every supported Windows.
rem It is more dependable than "net session", which also needs the Server
rem service running.
fltmc >nul 2>&1
if not errorlevel 1 goto :run

echo.
echo   nomad-setup needs Administrator rights to format an SD card.
echo   Asking Windows to re-launch it elevated - accept the prompt.
echo.

if "%~1"=="" (
  powershell -NoProfile -Command "try { Start-Process -FilePath '%~f0' -Verb RunAs } catch { exit 1 }"
) else (
  powershell -NoProfile -Command "try { Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs } catch { exit 1 }"
)

if errorlevel 1 (
  echo.
  echo   Elevation was declined or failed.
  echo.
  echo   Either right-click nomad-setup.bat and pick "Run as administrator",
  echo   or, if you only want to flash firmware and not touch a card:
  echo.
  echo       set NOMAD_SKIP_ELEVATE=1
  echo       .\nomad-setup.bat %*
  echo.
  pause
)
rem The elevated copy carries on in its own window; nothing more to do here.
exit /b

:run
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
rem An elevated window, or one started by double-clicking, closes the instant
rem the script ends and takes any error message with it. Hold it open in both
rem cases. Run from an already-elevated prompt, it returns immediately.
set "HOLD="
echo %cmdcmdline% | find /i "%~nx0" >nul && set "HOLD=1"
if defined HOLD (
  echo.
  echo   [nomad-setup exited with code %RC%]
  echo.
  pause
)
exit /b %RC%
