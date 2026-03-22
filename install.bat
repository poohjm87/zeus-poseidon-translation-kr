@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   Zeus + Poseidon Korean Patch Installer
echo ============================================
echo.

set GAME=C:\Program Files (x86)\Steam\steamapps\common\Zeus + Poseidon

if not exist "!GAME!\Zeus.exe" (
    echo [ERROR] Game folder not found.
    echo Install Zeus + Poseidon from Steam first.
    pause
    exit /b 1
)

set DIST=%~dp0
set PYTHON=!DIST!python\python.exe

if not exist "!PYTHON!" (
    echo [ERROR] python\python.exe not found in patch folder.
    pause
    exit /b 1
)

echo Game: !GAME!
echo.

if exist "!GAME!\Zeus_original.exe" goto skip_backup
echo [BACKUP] Backing up original files...
copy "!GAME!\Zeus.exe" "!GAME!\Zeus_original.exe" >nul
copy "!GAME!\Zeus_Text.eng" "!GAME!\Zeus_Text_original.eng" >nul
copy "!GAME!\Zeus_MM.eng" "!GAME!\Zeus_MM_original.eng" >nul
if exist "!GAME!\Model\Zeus eventmsg.txt" copy "!GAME!\Model\Zeus eventmsg.txt" "!GAME!\Model\Zeus eventmsg_original.txt" >nul
echo [BACKUP] Done
goto done_backup
:skip_backup
echo [BACKUP] Original backup exists. Skipping.
:done_backup

echo.
echo [PATCH] Patching EXE for Korean support...
"!PYTHON!" "!DIST!patch\patch_korean.py" --input "!GAME!\Zeus_original.exe" --output "!GAME!\Zeus.exe" --font-large "!DIST!patch\fonts\kfont_large_new.bin" --font-small "!DIST!patch\fonts\kfont_small_new.bin"
if errorlevel 1 (
    echo.
    echo [ERROR] EXE patch failed! Restoring original...
    copy /Y "!GAME!\Zeus_original.exe" "!GAME!\Zeus.exe" >nul
    pause
    exit /b 1
)
echo [PATCH] Done

echo.
echo [INSTALL] Copying translation files...
copy /Y "!DIST!Zeus_Text.eng" "!GAME!\Zeus_Text.eng" >nul
copy /Y "!DIST!Zeus_MM.eng" "!GAME!\Zeus_MM.eng" >nul

if exist "!DIST!Model\Zeus eventmsg.txt" (
    copy /Y "!DIST!Model\Zeus eventmsg.txt" "!GAME!\Model\Zeus eventmsg.txt" >nul
)

if exist "!DIST!Adventures" (
    xcopy /Y /E /Q "!DIST!Adventures\*" "!GAME!\Adventures\" >nul
)

echo.
echo ============================================
echo   Installation complete!
echo   Launch the game from Steam.
echo ============================================
pause
endlocal
