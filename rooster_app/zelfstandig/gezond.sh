#!/bin/sh
# HEALTHCHECK: /inloggen antwoordt altijd met 200, ook zonder wachtwoord.
# De poort komt uit PORT, zodat een andere POORT in .env niet "unhealthy" geeft.
set -eu
CONTROLE="import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/inloggen' % os.environ.get('PORT', '8100'), timeout=4)"
if [ "$(id -u)" = "0" ]; then
    exec su-exec nobody python3 -c "${CONTROLE}"
fi
exec python3 -c "${CONTROLE}"
