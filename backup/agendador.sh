#!/bin/sh
# Faz um backup ao subir o container e depois todo dia no HORA_BACKUP (horário de Brasília).
set -eu
/backup.sh || echo "[backup] falhou ao iniciar; tento de novo no próximo horário"
while true; do
  agora=$(date +%s)
  alvo=$(date -d "$(date +%Y-%m-%d) ${HORA_BACKUP:-04:00}" +%s)
  [ "$alvo" -le "$agora" ] && alvo=$((alvo + 86400))
  sleep $((alvo - agora))
  /backup.sh || echo "[backup] falhou; tento de novo amanhã"
done
