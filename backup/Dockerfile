FROM mysql:8.4
# mysql:8.4 é baseada em Oracle Linux: tem mysqldump, gzip e date com -d
COPY backup.sh agendador.sh restaurar.sh /
RUN chmod +x /backup.sh /agendador.sh /restaurar.sh
ENTRYPOINT ["/agendador.sh"]
