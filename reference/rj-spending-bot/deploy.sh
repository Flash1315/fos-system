#!/bin/bash
set -e

echo "🚀 Deploying to server..."
git add .
git commit -m "${1:-update}"
git push origin dev

echo "✅ Pushed to GitHub (dev)."
echo "   GitHub Actions задеплоит на сервер автоматически."
echo "   Статус: https://github.com/Flash1315/RJ-Spending-bot/actions"
