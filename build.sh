#!/usr/bin/env bash
# Render runs this on every deploy (see render.yaml).
set -o errexit -o nounset -o pipefail

pip install -r requirements.txt
bin/tailwind -i assets/app.css -o static/dist/app.css --minify
python manage.py collectstatic --no-input
# Render's free tier has no separate pre-deploy step, so migrations run here.
python manage.py migrate --no-input
