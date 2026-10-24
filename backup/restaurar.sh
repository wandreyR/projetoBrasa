#!/bin/sh
# Restaura um backup (APAGA os dados atuais do banco e coloca os do arquivo).
# Uso:  docker compose exec backup /restaurar.sh brasa_2026-10-23_0400.sql.gz
set -eu
[ $# -eq 1 ] || { echo "Uso: /restaurar.sh <arquivo em /backups>"; ls /backups; exit 1; }
gunzip -c "/backups/$1" | mysql -h db -uroot -p"$DB_PASSWORD" "$DB_NAME"
echo "[backup] restaurado: $1 — reinicie o backend: docker compose restart backend"
