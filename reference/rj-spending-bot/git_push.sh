#!/bin/bash
cd /root/rjbot
git add .
git commit -m "Auto-backup $(date '+%Y-%m-%d %H:%M')" 2>/dev/null
git push origin main 2>/dev/null
