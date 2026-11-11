#!/bin/sh
# Roda só na primeira subida do banco (volume vazio): restaura o dump do hackathon.
set -e
DUMP=/dump/fortuna_hackathon.dump
if [ ! -s "$DUMP" ]; then
    echo "ERRO: dump não encontrado. Coloque fortuna_hackathon.dump na raiz do projeto ou defina FORTUNA_DUMP." >&2
    exit 1
fi
echo "restaurando $DUMP no banco $POSTGRES_DB"
pg_restore --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$DUMP"
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT tipo_base, count(*) FROM hackathon.pedidos GROUP BY 1 ORDER BY 1"
