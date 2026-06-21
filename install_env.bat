@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "ENV_NAME=eft-raid-assistant"
set "LOG_FILE=%~dp0install_log.txt"
set "CONDA_EXE="
set "CONDA_ACTIVATE="
set "SETUP_TMP=%TEMP%\eft_raid_assistant_setup"
set "SETUP_ENV_FILE=%SETUP_TMP%\environment.yml"
set "SETUP_REQ_FILE=%SETUP_TMP%\requirements.txt"
set "CONDA_NO_PLUGINS=true"

echo EFT Raid Assistant install log > "!LOG_FILE!"
echo Started at %DATE% %TIME% >> "!LOG_FILE!"
echo Folder: %CD% >> "!LOG_FILE!"
echo. >> "!LOG_FILE!"

set "APP_DIR=%CD%"
if /I "!APP_DIR:~0,16!"=="C:\Program Files" (
    echo.
    echo Please move this folder out of Program Files first.
    echo Recommended path: C:\EFT-Raid-Assistant-Test
    echo.
    echo Program Files is not supported for this test package. >> "!LOG_FILE!"
    echo Recommended path: C:\EFT-Raid-Assistant-Test >> "!LOG_FILE!"
    echo.
    echo A log was written to:
    echo !LOG_FILE!
    pause
    exit /b 1
)

if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" (
    set "CONDA_EXE=%USERPROFILE%\miniconda3\Scripts\conda.exe"
    set "CONDA_ACTIVATE=%USERPROFILE%\miniconda3\Scripts\activate.bat"
) else if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" (
    set "CONDA_EXE=%USERPROFILE%\anaconda3\Scripts\conda.exe"
    set "CONDA_ACTIVATE=%USERPROFILE%\anaconda3\Scripts\activate.bat"
) else if exist "%LOCALAPPDATA%\miniconda3\Scripts\conda.exe" (
    set "CONDA_EXE=%LOCALAPPDATA%\miniconda3\Scripts\conda.exe"
    set "CONDA_ACTIVATE=%LOCALAPPDATA%\miniconda3\Scripts\activate.bat"
) else (
    for /f "delims=" %%I in ('where conda 2^>nul') do (
        if not defined CONDA_EXE set "CONDA_EXE=%%I"
    )
)

if not defined CONDA_EXE (
    echo Could not find conda.
    echo Could not find conda. >> "!LOG_FILE!"
    echo.
    echo Please install Miniconda or Anaconda first, then run this file again.
    echo Recommended: https://docs.conda.io/en/latest/miniconda.html
    echo.
    echo A log was written to:
    echo !LOG_FILE!
    pause
    exit /b 1
)

echo Using conda: !CONDA_EXE!
echo Using conda: !CONDA_EXE! >> "!LOG_FILE!"

if not exist "!SETUP_TMP!" mkdir "!SETUP_TMP!"
copy /Y "%~dp0environment.yml" "!SETUP_ENV_FILE!" >> "!LOG_FILE!" 2>&1
copy /Y "%~dp0requirements.txt" "!SETUP_REQ_FILE!" >> "!LOG_FILE!" 2>&1

if errorlevel 1 (
    echo.
    echo Failed to prepare setup files.
    echo Failed to prepare setup files. >> "!LOG_FILE!"
    echo Please try moving this folder to C:\EFT-Raid-Assistant-Test and run again.
    echo.
    echo A log was written to:
    echo !LOG_FILE!
    pause
    exit /b 1
)

echo.
echo Environment: %ENV_NAME%
echo Setup files: !SETUP_TMP!
echo Environment: %ENV_NAME% >> "!LOG_FILE!"
echo Setup files: !SETUP_TMP! >> "!LOG_FILE!"
echo. >> "!LOG_FILE!"

"!CONDA_EXE!" run -n "%ENV_NAME%" python --version >> "!LOG_FILE!" 2>&1
if errorlevel 1 (
    echo Creating conda environment...
    echo Creating conda environment... >> "!LOG_FILE!"
    echo Removing any broken old environment first... >> "!LOG_FILE!"
    "!CONDA_EXE!" env remove -n "%ENV_NAME%" -y >> "!LOG_FILE!" 2>&1
    "!CONDA_EXE!" create -y -n "%ENV_NAME%" -c conda-forge python=3.11 pip tesseract >> "!LOG_FILE!" 2>&1
) else (
    echo Updating conda packages...
    echo Updating conda packages... >> "!LOG_FILE!"
    "!CONDA_EXE!" install -y -n "%ENV_NAME%" -c conda-forge python=3.11 pip tesseract >> "!LOG_FILE!" 2>&1
)

if errorlevel 1 (
    echo.
    echo Failed to create or update the conda environment.
    echo Failed to create or update the conda environment. >> "!LOG_FILE!"
    echo.
    echo Try moving the app folder to C:\EFT-Raid-Assistant-Test and run this file again.
    echo.
    echo A log was written to:
    echo !LOG_FILE!
    pause
    exit /b 1
)

echo.
echo Installing Python packages with pip...
echo Installing Python packages with pip... >> "!LOG_FILE!"
"!CONDA_EXE!" run -n "%ENV_NAME%" python -m pip install -r "!SETUP_REQ_FILE!" >> "!LOG_FILE!" 2>&1

if errorlevel 1 (
    echo.
    echo Failed to install Python packages.
    echo Failed to install Python packages. >> "!LOG_FILE!"
    echo Please check your internet connection, then run this file again.
    echo.
    echo A log was written to:
    echo !LOG_FILE!
    pause
    exit /b 1
)

if defined CONDA_ACTIVATE (
    call "!CONDA_ACTIVATE!" "%ENV_NAME%"
) else (
    call conda activate "%ENV_NAME%"
)

if errorlevel 1 (
    echo.
    echo Environment was installed, but activation failed.
    echo Environment was installed, but activation failed. >> "!LOG_FILE!"
    echo Try opening Anaconda Prompt in this folder and run:
    echo conda activate %ENV_NAME%
    echo.
    echo A log was written to:
    echo !LOG_FILE!
    pause
    exit /b 1
)

set "TESSDATA_DIR=%CONDA_PREFIX%\Library\share\tessdata"
if not exist "!TESSDATA_DIR!" mkdir "!TESSDATA_DIR!"

echo.
echo Installing Tesseract language data...
echo Installing Tesseract language data... >> "!LOG_FILE!"
if not exist "!TESSDATA_DIR!\eng.traineddata" (
    curl.exe -L --fail -o "!TESSDATA_DIR!\eng.traineddata" "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata" >> "!LOG_FILE!" 2>&1
)
if not exist "!TESSDATA_DIR!\chi_sim.traineddata" (
    curl.exe -L --fail -o "!TESSDATA_DIR!\chi_sim.traineddata" "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/chi_sim.traineddata" >> "!LOG_FILE!" 2>&1
)

echo.
echo Installed OCR languages:
tesseract --list-langs
tesseract --list-langs >> "!LOG_FILE!" 2>&1

echo.
echo Setup complete. You can now run start_eft_raid_assistant.bat.
echo Setup complete. >> "!LOG_FILE!"
pause

endlocal
