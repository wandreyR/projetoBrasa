#!/bin/sh
# Faz um dump do MySQL compactado em /backups e apaga os mais antigos que DIAS_RETENCAO.
# Rodar na mão:   docker compose exec backup /backup.sh
set -eu
ARQUIVO="/backups/brasa_$(date +%Y-%m-%d_%H%M).sql.gz"
mysqldump -h db -uroot -p"$DB_PASSWORD" --single-transaction --routines --no-tablespaces "$DB_NAME" | gzip > "$ARQUIVO.tmp"
mv "$ARQUIVO.tmp" "$ARQUIVO"
find /backups -name 'brasa_*.sql.gz' -mtime +"${DIAS_RETENCAO:-14}" -delete
echo "[backup] $(date '+%d/%m/%Y %H:%M') -> $ARQUIVO ($(du -h "$ARQUIVO" | cut -f1))"
