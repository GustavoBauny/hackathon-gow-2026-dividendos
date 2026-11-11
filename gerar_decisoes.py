#!/usr/bin/env python
"""Gera o arquivo de decisões do time Dividendos do zero.

    banco (PostgreSQL) -> bureau (API, com retry e cache) -> features -> modelo de risco -> política -> CSV

Uso:
    python gerar_decisoes.py                       # dividendos_final.csv + artefatos do painel em data/
    python gerar_decisoes.py --saida outro.csv
    python gerar_decisoes.py --sem-cache-bureau    # ignora o cache e consulta o bureau de novo

A política usada é a aprovada pelo analista no painel (politica_aprovada.json). Sem aprovação
gravada, usa a proposta da IA (regras padrão de src/politica.py).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "src"))

import pandas as pd  # noqa: E402

from bureau_client import BureauClient  # noqa: E402
from db import carregar  # noqa: E402
from features import montar_base  # noqa: E402
from padroes import calcular_padroes  # noqa: E402
from politica import (carregar_parametros, parametros_dict, politica_atual, politica_nova,  # noqa: E402
                      resultado_esperado)
from risco import ModeloRisco  # noqa: E402
from target import construir_alvo  # noqa: E402
from validacao import publicar_csv  # noqa: E402

log = logging.getLogger("pipeline")
DADOS = RAIZ / "data"
POLITICA_APROVADA = RAIZ / "politica_aprovada.json"   # versão aprovada pelo analista no painel


def resumo_tentativas(regs: list[dict]) -> dict:
    """Em que tentativa cada resposta válida chegou (fica no cache: vale também para reexecuções)."""
    t = pd.Series([r["tentativas"] for r in regs if r.get("status") == "ok" and "tentativas" in r], dtype=int)
    return {"tentativas_por_cliente": {int(k): int(v) for k, v in t.value_counts().sort_index().items()},
            "clientes_com_retry": int((t > 1).sum()), "tentativas_max": int(t.max()) if len(t) else 0}


def consultar_bureau(ids: list[str], sem_cache: bool) -> tuple[pd.DataFrame, dict]:
    cache = DADOS / "bureau_cache.jsonl"
    if sem_cache and cache.exists():
        cache.rename(cache.with_suffix(f".{int(time.time())}.bak"))
    cli = BureauClient(cache_path=cache)
    regs = cli.consultar_lote(ids)
    df = pd.DataFrame(regs)
    stats = cli.stats.resumo()
    stats["status"] = df["status"].value_counts().to_dict()
    stats.update(resumo_tentativas(regs))
    log.info("bureau: %s", stats)
    return df[df["status"] == "ok"].copy(), stats


def resumir(dec: pd.DataFrame, ev: pd.Series) -> dict:
    ap = dec["decisao"] == "APROVADO"
    return {"aprovados": int(ap.sum()), "valor_total": round(float(dec.loc[ap, "valor_aprovado"].sum()), 2),
            "resultado_esperado": round(float(ev.sum()), 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", default=str(RAIZ / "dividendos_final.csv"))
    ap.add_argument("--sem-cache-bureau", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("bureau").setLevel(logging.WARNING)
    DADOS.mkdir(exist_ok=True)
    t0 = time.time()

    # 1. dados
    d = carregar()
    ped = d["pedidos"]
    novos_ids = ped.loc[ped["tipo_base"] == "novo", "id_cliente"].tolist()
    log.info("pedidos: %s", ped["tipo_base"].value_counts().to_dict())

    # 2. bureau dos pedidos novos (timeout, retry com backoff, cache em disco)
    bureau_novos, stats_bureau = consultar_bureau(novos_ids, args.sem_cache_bureau)

    # 3. features e alvo com censura
    base = montar_base(d, bureau_novos)
    alvo = construir_alvo(ped, d["parcelas"])
    hist = base[base["tipo_base"] == "historico"].merge(
        alvo.drop(columns=["prazo_meses", "valor_aprovado", "situacao_final"]), on="id_pedido", how="left")
    hist_ap = hist[hist["decisao"] == "aprovado"].copy()
    vazias = ["decisao", "valor_aprovado", "politica_aplicada", "situacao_final"]  # sem valor nos novos
    novos = base[base["tipo_base"] == "novo"].drop(columns=vazias).sort_values("id_pedido").reset_index(drop=True)

    # 4. modelo de risco explicável (Poisson com exposição + logística de atraso), ajustado no histórico
    modelo = ModeloRisco().fit(hist_ap)
    log.info("modelo: risco base %.1f%%, fatores %s", 100 * modelo.pd_base(),
             {k: v["rr"] for k, v in modelo.diagnostico["calote"]["fatores"].items() if k != "const"})

    # 5. política (versão aprovada pelo analista, ou a proposta da IA) e política atual nos pedidos novos
    params = carregar_parametros(POLITICA_APROVADA)
    origem = "politica_aprovada.json" if POLITICA_APROVADA.exists() else "proposta da IA (sem aprovação gravada)"
    log.info("política: %s", origem)
    dec = politica_nova(novos, modelo, params)
    atual = politica_atual(novos)
    ev_nova = resultado_esperado(dec, novos, modelo)
    ev_atual = resultado_esperado(atual, novos, modelo)

    # 6. arquivo oficial + validação no formato da organização
    # (grava num candidato, confere e só então troca o oficial: um erro nunca destrói o último arquivo bom)
    saida = Path(args.saida)
    rel = publicar_csv(dec[["id_pedido", "decisao", "valor_aprovado"]], saida, novos[["id_pedido", "valor_solicitado"]])
    log.info("validação: %s", {k: v for k, v in rel.items() if k != "problemas"})
    if not rel["ok"]:
        log.error("arquivo com problemas, oficial anterior mantido; candidato em %s: %s", rel["arquivo"], rel["problemas"])
        return 1

    # 7. artefatos para o painel
    det = novos.join(dec.drop(columns=["id_pedido"]))
    det["decisao_atual"], det["valor_atual"] = atual["decisao"].values, atual["valor_aprovado"].values
    det["ev_modelo"], det["ev_modelo_atual"] = ev_nova.values, ev_atual.values
    det.to_parquet(DADOS / "decisoes_detalhadas.parquet")
    novos.to_parquet(DADOS / "novos_base.parquet")
    hist.to_parquet(DADOS / "hist_base.parquet")
    modelo.salvar(DADOS / "modelo_risco.json")
    padroes = calcular_padroes(hist, novos, d["parcelas"])
    (DADOS / "padroes.json").write_text(json.dumps(padroes, ensure_ascii=False, indent=2), encoding="utf-8")

    resumo = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "arquivo": saida.name,
        "politica_usada": origem,
        "validacao": rel,
        "bureau": stats_bureau,
        "modelo": modelo.diagnostico,
        "parametros": parametros_dict(params),
        "nova": {**resumir(dec, ev_nova), "por_passo": {int(k): int(v) for k, v in dec["passo"].value_counts().sort_index().items()},
                 "motivos": dec["motivo"].value_counts().to_dict()},
        "atual": resumir(atual, ev_atual),
        "divergencias_vs_atual": int((dec["decisao"].values != atual["decisao"].values).sum()),
        "tempo_s": round(time.time() - t0, 1),
    }
    (DADOS / "resumo_execucao.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: resumo[k] for k in ("arquivo", "politica_usada", "nova", "atual", "divergencias_vs_atual", "tempo_s")},
                     ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
