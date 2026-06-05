@echo off
cd /d f:\MCP_tool

echo ═══════════════════════════════════════════
echo   MCP Document Editor — Setup
echo ═══════════════════════════════════════════
echo.

:: Check for uv
where uv >nul 2>nul
if %ERRORLEVEL% neq 0 goto USE_PIP

echo [1/2] Installing dependencies using uv...
uv sync
if %ERRORLEVEL% neq 0 goto UV_FAILED
goto SETUP_COMPLETE

:USE_PIP
echo [INFO] 'uv' package manager not found. Falling back to standard 'pip'...
echo.
echo [1/2] Installing dependencies using pip...
pip install -e .
if %ERRORLEVEL% neq 0 goto PIP_FAILED
goto SETUP_COMPLETE

:UV_FAILED
echo [ERROR] Dependency installation failed using uv.
pause
exit /b 1

:PIP_FAILED
echo [ERROR] Dependency installation failed using pip.
pause
exit /b 1

:SETUP_COMPLETE
echo.
echo [2/2] Setup complete!
echo.
echo ═══════════════════════════════════════════
echo   Usage:
echo     python main.py web           Start editor
echo     python main.py web --port 9000  Custom port
echo     python main.py dev           Start MCP + Web
echo     python main.py admin         Desktop GUI
echo ═══════════════════════════════════════════
echo.
pause
