#!/bin/bash
# Deploy/update steps for cPanel + terminal. Run from project root:
#   bash deploy.sh
# Or: chmod +x deploy.sh && ./deploy.sh

set -e
echo "=== Deploy: install, migrate, collectstatic, restart ==="

pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput

mkdir -p tmp
touch tmp/restart.txt
echo "=== Done. App restarted (Passenger). ==="
