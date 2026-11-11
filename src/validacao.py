"""Gravação e validação do arquivo de decisões no formato exigido pela organização.

Formato (manual, seção 5.2): UTF-8, vírgula, ponto decimal com 2 casas, cabeçalho exato
`id_pedido,decisao,valor_aprovado`, uma linha por pedido novo, APROVADO/NEGADO em maiúsculas,
valor > 0 quando aprovado e 0.00 quando negado. Limites do produto: R$ 500 a R$ 30.000 e nunca
acima do valor solicitado.
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path

import pandas as pd

CABECALHO = ["id_pedido", "decisao", "valor_aprovado"]
VALOR_MIN, VALOR_MAX = 500.0, 30000.0
_RE_VALOR = re.compile(r"^\d+\.\d{2}$")


def gravar_csv(decisoes: pd.DataFrame, caminho: str | Path) -> Path:
    """Grava o CSV oficial. Ordena por id_pedido e formata o valor com 2 casas."""
    caminho = Path(caminho)
    d = decisoes.sort_values("id_pedido")
    with caminho.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(CABECALHO)
        for idp, dec, val in zip(d["id_pedido"], d["decisao"], d["valor_aprovado"]):
            w.writerow([idp, dec, f"{(float(val) if dec == 'APROVADO' else 0.0):.2f}"])
    return caminho


def validar_csv(caminho: str | Path, novos: pd.DataFrame) -> dict:
    """Confere o arquivo como a organização confere. `novos`: id_pedido e valor_solicitado dos pedidos novos.

    Devolve um relatório parecido com o do checkpoint e a lista de problemas (vazia = arquivo ok).
    """
    caminho = Path(caminho)
    problemas: list[str] = []
    bruto = caminho.read_bytes()
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "problemas": ["arquivo não está em UTF-8"]}
    if texto.startswith("﻿"):
        problemas.append("arquivo começa com BOM")
    if "\r" in texto:
        problemas.append("quebra de linha com \\r (CRLF)")

    linhas = list(csv.reader(texto.splitlines()))
    if not linhas or linhas[0] != CABECALHO:
        problemas.append(f"cabeçalho diferente de {','.join(CABECALHO)}: {linhas[0] if linhas else None}")
    corpo = linhas[1:]

    solicitado = dict(zip(novos["id_pedido"], novos["valor_solicitado"].astype(float)))
    vistos: set[str] = set()
    aprovados = negados = 0
    total = 0.0
    for n, row in enumerate(corpo, start=2):
        if len(row) != 3:
            problemas.append(f"linha {n}: {len(row)} colunas")
            continue
        idp, dec, val = row
        if idp not in solicitado:
            problemas.append(f"linha {n}: id_pedido {idp} não está na base de novos")
            continue
        if idp in vistos:
            problemas.append(f"linha {n}: id_pedido {idp} repetido")
            continue
        vistos.add(idp)
        if dec not in ("APROVADO", "NEGADO"):
            problemas.append(f"linha {n}: decisao inválida {dec!r}")
            continue
        if not _RE_VALOR.match(val):
            problemas.append(f"linha {n}: valor fora do formato 0.00: {val!r}")
            continue
        v = float(val)
        if dec == "NEGADO":
            negados += 1
            if v != 0:
                problemas.append(f"linha {n}: negado com valor {val}")
        else:
            aprovados += 1
            total += v
            if v < VALOR_MIN:
                problemas.append(f"linha {n}: aprovado abaixo de R$ 500 ({val})")
            if v > VALOR_MAX + 1e-9:
                problemas.append(f"linha {n}: aprovado acima de R$ 30.000 ({val})")
            if v > solicitado[idp] + 1e-9:
                problemas.append(f"linha {n}: aprovado acima do solicitado ({val} > {solicitado[idp]:.2f})")
    faltando = set(solicitado) - vistos
    if faltando:
        problemas.append(f"{len(faltando)} pedidos novos ausentes do arquivo")
    return {
        "ok": not problemas,
        "linhas": len(corpo),
        "pedidos_com_decisao": len(vistos),
        "aprovados": aprovados,
        "negados": negados,
        "valor_total_aprovado": round(total, 2),
        "problemas": problemas[:50],
    }


def publicar_csv(decisoes: pd.DataFrame, destino: str | Path, novos: pd.DataFrame) -> dict:
    """Grava num arquivo candidato, confere e só então troca o oficial (troca atômica).

    Se a conferência falhar, o arquivo oficial anterior fica intacto e o candidato fica ao lado
    (`<nome>.candidato.csv`) para inspeção. Assim uma reexecução com problema nunca destrói o
    último arquivo bom.
    """
    destino = Path(destino)
    candidato = destino.with_name(destino.stem + ".candidato.csv")
    gravar_csv(decisoes, candidato)
    rel = validar_csv(candidato, novos)
    if rel["ok"]:
        os.replace(candidato, destino)
    rel["arquivo"] = str(destino if rel["ok"] else candidato)
    return rel
