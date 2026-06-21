@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "ENV_NAME=eft-raid-assistant"
set "LOG_FILE=%~dp0startup_log.txt"
set "CONDA_EXE="

echo EFT Raid Assistant startup log > "!LOG_FILE!"
echo Started at %DATE% %TIME% >> "!LOG_FILE!"
echo Folder: %CD% >> "!LOG_FILE!"
echo. >> "!LOG_FILE!"

if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" (
    set "CONDA_EXE=%USERPROFILE%\miniconda3\Scripts\conda.exe"
) else if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" (
    set "CONDA_EXE=%USERPROFILE%\anaconda3\Scripts\conda.exe"
) else if exist "%LOCALAPPDATA%\miniconda3\Scripts\conda.exe" (
    set "CONDA_EXE=%LOCALAPPDATA%\miniconda3\Scripts\conda.exe"
) else (
    for /f "delims=" %%I in ('where conda 2^>nul') do (
        if not defined CONDA_EXE set "CONDA_EXE=%%I"
    )
)

if not defined CONDA_EXE (
    echo Could not find conda.
    echo Could not find conda. >> "!LOG_FILE!"
    echo.
    echo Please install Miniconda or Anaconda first.
    echo Then run install_env.bat before starting the app.
    echo.
    echo A log was written to:
    echo !LOG_FILE!
    pause
    exit /b 1
)

echo Using conda: !CONDA_EXE!
echo Using conda: !CONDA_EXE! >> "!LOG_FILE!"

"!CONDA_EXE!" info --envs >> "!LOG_FILE!" 2>&1
echo. >> "!LOG_FILE!"

"!CONDA_EXE!" run -n "%ENV_NAME%" python --version >> "!LOG_FILE!" 2>&1
if errorlevel 1 (
    echo.
    echo Could not run Python in environment: %ENV_NAME%
    echo Please run install_env.bat first.
    echo If install failed before, remove the broken environment and reinstall.
    echo.
    echo Could not run Python in environment: %ENV_NAME% >> "!LOG_FILE!"
    echo Suggested repair: conda env remove -n %ENV_NAME%, then run install_env.bat >> "!LOG_FILE!"
    echo A log was written to:
    echo !LOG_FILE!
    pause
    exit /b 1
)

echo.
echo Starting app...
echo Starting app... >> "!LOG_FILE!"
echo.

"!CONDA_EXE!" run --no-capture-output -n "%ENV_NAME%" python main.py >> "!LOG_FILE!" 2>&1

if errorlevel 1 (
    echo.
    echo App exited with an error.
    echo App exited with an error. >> "!LOG_FILE!"
    echo.
    echo Please send this file back for debugging:
    echo !LOG_FILE!
    pause
    exit /b 1
)

endlocal
