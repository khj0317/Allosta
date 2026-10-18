@echo off
rem Runs dev.ps1 regardless of PowerShell execution policy. Usage: dev.cmd [-Seed]
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" %*
