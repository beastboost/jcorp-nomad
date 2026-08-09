@echo off
REM ============================================================================
REM  update.bat - fetch the latest Jcorp Nomad code.
REM
REM  Works whether you cloned the repo or unzipped it:
REM
REM    already a git clone   ->  git pull
REM    an unzipped folder    ->  converted into a clone in place, once, then
REM                              every later run is a plain pull
REM    no git installed      ->  downloads the zip and unpacks it over the top
REM
REM  Double-click it, or run it from a terminal. Takes no arguments.
REM ============================================================================
setlocal EnableDelayedExpansion

set "REPO_URL=https://github.com/beastboost/jcorp-nomad.git"
set "ZIP_URL=https://github.com/beastboost/jcorp-nomad/archive/refs/heads/main.zip"
set "BRANCH=main"

REM The repo root is the parent of tools\, wherever this file happens to live.
cd /d "%~dp0.."
set "ROOT=%CD%"
echo.
echo   Jcorp Nomad updater
echo   -------------------
echo   Folder: %ROOT%
echo.

where git >nul 2>&1
if errorlevel 1 goto :nogit

if exist ".git" goto :pull

REM -------------------------------------------------- unzipped folder -------
echo   This folder is not a git clone yet. Converting it into one so that
echo   future updates are a simple pull.
echo.
echo   Files tracked by the repository will be replaced with the latest
echo   versions. Anything you added yourself is left alone.
echo.
set /p "REPLY=  Continue? [Y/n] "
if /i "!REPLY!"=="n" goto :cancelled

git init -q
if errorlevel 1 goto :gitfail
git remote remove origin >nul 2>&1
git remote add origin "%REPO_URL%"
if errorlevel 1 goto :gitfail

echo   Fetching %BRANCH% ...
set "FETCH_ARGS=--depth 1"
call :fetch_with_retry
if errorlevel 1 goto :gitfail

git checkout -f -B %BRANCH% origin/%BRANCH%
if errorlevel 1 goto :gitfail
goto :done

REM ------------------------------------------------------ existing clone ----
:pull
for /f "delims=" %%d in ('git status --porcelain 2^>nul') do set "DIRTY=1"
if defined DIRTY (
  echo   You have local changes to tracked files:
  echo.
  git status --short
  echo.
  echo   A pull may conflict with them. Stash them first if you want to
  echo   keep them:   git stash
  echo.
  set /p "REPLY=  Pull anyway? [y/N] "
  if /i not "!REPLY!"=="y" goto :cancelled
)

echo   Pulling %BRANCH% ...
set "FETCH_ARGS="
call :fetch_with_retry
if errorlevel 1 goto :gitfail
git merge --ff-only origin/%BRANCH%
if errorlevel 1 (
  echo.
  echo   Could not fast-forward - your branch has diverged from origin.
  echo   To throw away local commits and match GitHub exactly:
  echo.
  echo       git reset --hard origin/%BRANCH%
  echo.
  goto :failed
)
goto :done

REM ------------------------------------------------------------ no git ------
:nogit
echo   git is not installed, so falling back to downloading the zip.
echo   Installing git makes this much faster:  winget install Git.Git
echo.
set "TMPZIP=%TEMP%\jcorp-nomad-update.zip"
set "TMPDIR=%TEMP%\jcorp-nomad-update"

echo   Downloading ...
powershell -NoProfile -Command ^
  "$ErrorActionPreference='Stop'; Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%TMPZIP%'"
if errorlevel 1 goto :failed

if exist "%TMPDIR%" rmdir /s /q "%TMPDIR%"
echo   Unpacking ...
powershell -NoProfile -Command ^
  "$ErrorActionPreference='Stop'; Expand-Archive -Path '%TMPZIP%' -DestinationPath '%TMPDIR%' -Force"
if errorlevel 1 goto :failed

REM The archive contains a single top-level jcorp-nomad-main\ directory.
for /d %%D in ("%TMPDIR%\*") do (
  echo   Copying files into place ...
  robocopy "%%~fD" "%ROOT%" /E /NFL /NDL /NJH /NJS /NP >nul
  if errorlevel 8 goto :failed
)
del /q "%TMPZIP%" >nul 2>&1
rmdir /s /q "%TMPDIR%" >nul 2>&1
goto :done

REM ----------------------------------------------------------- helpers ------
:fetch_with_retry
REM FETCH_ARGS is "--depth 1" only for the first-time conversion, where it saves
REM pulling the whole history. Using it on an existing clone would make that
REM clone shallow, which breaks later merges.
REM Network hiccups are common enough to be worth four tries.
set "WAIT=2"
for /l %%i in (1,1,4) do (
  git fetch !FETCH_ARGS! origin %BRANCH%
  if not errorlevel 1 exit /b 0
  echo   fetch failed, retrying in !WAIT!s ...
  timeout /t !WAIT! /nobreak >nul
  set /a WAIT=!WAIT!*2
)
git fetch !FETCH_ARGS! origin %BRANCH%
exit /b %errorlevel%

:gitfail
echo.
echo   git reported an error - see the output above.
goto :failed

:cancelled
echo.
echo   Nothing changed.
goto :end

:failed
echo.
echo   Update FAILED. Nothing was flashed or erased; only files in
echo   %ROOT% would have changed.
set "RC=1"
goto :end

:done
echo.
echo   Up to date.
for /f "delims=" %%c in ('git log -1 --pretty^=format:"%%h  %%s" 2^>nul') do echo   Now at: %%c
echo.
echo   Next:  .\nomad-setup.bat flash
set "RC=0"

:end
REM Hold the window open when launched from Explorer rather than a terminal.
echo %cmdcmdline% | find /i "%~0" >nul
if not errorlevel 1 pause
exit /b %RC%
