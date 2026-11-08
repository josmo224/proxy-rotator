@echo off
REM Daily refresh: download new proxies, re-check known ones, rebuild proxies.txt.
cd /d "%~dp0"
python fetch_proxies.py --recheck-hours 24 --concurrency 400 --timeout 6
