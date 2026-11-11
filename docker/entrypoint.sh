#!/bin/sh
# Roda o comando e, no fim, devolve output/ e data/ ao dono da pasta output/ do host.
# Sem isso, no Linux, os arquivos gerados ficariam com dono root.
"$@"
status=$?
if [ "$(id -u)" = 0 ] && dono=$(stat -c %u:%g /app/output 2>/dev/null); then
    chown -R "$dono" /app/output /app/data 2>/dev/null || true
fi
exit $status
