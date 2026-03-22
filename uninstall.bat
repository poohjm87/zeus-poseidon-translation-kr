@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   Zeus + Poseidon Korean Patch Uninstaller
echo ============================================
echo.

set GAME=C:\Program Files (x86)\Steam\steamapps\common\Zeus + Poseidon

if not exist "!GAME!\Zeus_original.exe" (
    echo [ERROR] Original backup not found.
    echo Use Steam "Verify integrity of game files" instead.
    pause
    exit /b 1
)

echo [RESTORE] Restoring original files...
copy /Y "!GAME!\Zeus_original.exe" "!GAME!\Zeus.exe" >nul
copy /Y "!GAME!\Zeus_Text_original.eng" "!GAME!\Zeus_Text.eng" >nul
copy /Y "!GAME!\Zeus_MM_original.eng" "!GAME!\Zeus_MM.eng" >nul

if exist "!GAME!\Model\Zeus eventmsg_original.txt" (
    copy /Y "!GAME!\Model\Zeus eventmsg_original.txt" "!GAME!\Model\Zeus eventmsg.txt" >nul
)

echo.
echo ============================================
echo   Original files restored!
echo ============================================
pause
endlocal
