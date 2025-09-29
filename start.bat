@echo off
for /f "tokens=1,2 delims==" %%a in (parameters.env) do set %%a=%%b
mcpo --port 8001 -- py server.py