@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 ac_bench_gui.py
    goto done
)
where python >nul 2>nul
if %errorlevel%==0 (
    python ac_bench_gui.py
    goto done
)
echo Python was not found.
pause
exit /b 1
:done
