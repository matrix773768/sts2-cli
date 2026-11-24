@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0inf1.ps1" start
exit /b %ERRORLEVEL%
