#!/bin/sh
# Start Rooster als losse container (zonder Home Assistant).
set -eu
: "${PUID:=1000}" "${PGID:=1000}" "${DATA_DIR:=/data}" "${PORT:=8100}" "${TZ:=Europe/Amsterdam}"

# Met 0 zou de app als root draaien. Een fout in de app kan dan alles in de
# container; liever niet starten.
for naam in PUID PGID; do
    eval "waarde=\${${naam}}"
    case "${waarde}" in
        ''|*[!0-9]*|0)
            echo "${naam}=${waarde} kan niet. Zet in .env wat id -u en id -g zeggen (niet 0)." >&2
            exit 1 ;;
    esac
done

echo "Rooster wordt gestart op poort ${PORT} (tijdzone ${TZ})..."
if [ "$(id -u)" = "0" ]; then
    # Docker maakt ./data als root aan, en een back-up uit Home Assistant is
    # ook van root. Alleen wat niet klopt, zodat een herstart snel blijft.
    mkdir -p "${DATA_DIR}"
    find "${DATA_DIR}" \( ! -user "${PUID}" -o ! -group "${PGID}" \) -exec chown -h "${PUID}:${PGID}" {} +
    exec su-exec "${PUID}:${PGID}" python3 /opt/app/main.py
fi
exec python3 /opt/app/main.py
