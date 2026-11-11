"""Evidências no histórico para o painel (output/avaliacao.json). Não é necessário para gerar o CSV.

1. Validação fora do tempo: treina só com pedidos até set/2025 e prevê os calotes dos trimestres seguintes
   (inclui todo o piloto, que o modelo não viu).
2. Backtest cross-fitted: cada pedido histórico é decidido por um modelo que não o viu no treino;
   compara política atual x proposta pelo resultado esperado (+15% / +5% / -60%).
3. Sensibilidade a parâmetros da política (margem mínima, teto de parcela sobre a sobra).
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "src"))

from db import carregar  # noqa: E402
from features import montar_base  # noqa: E402
from target import construir_alvo  # noqa: E402
from modelo import ModeloCalote, ModeloEnsemble  # noqa: E402
from politica import Parametros, politica_atual, politica_nova, resultado_esperado, taxa_atraso_por_segmento  # noqa: E402

log = logging.getLogger("avaliacao")


def main(n_folds: int = 5):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    t0 = time.time()
    d = carregar()
    alvo = construir_alvo(d["pedidos"], d["parcelas"])
    base = montar_base(d)
    hb = base[base["tipo_base"] == "historico"].reset_index(drop=True)
    hist = hb.merge(alvo[["id_pedido", "n_observaveis", "calote_obs", "k_evento", "exposicao", "frac_vencida",
                          "atraso_obs"]], on="id_pedido")
    L = taxa_atraso_por_segmento(hist)

    # 1. fora do tempo
    corte = "2025-10-01"
    m = ModeloCalote().fit(hist[hist["data_pedido"] < corte], d["parcelas"])
    hist["pd_ate_corte"] = m.pd_contrato(hist, hist["valor_aprovado"], ate_parcela=hist["n_observaveis"])
    hist["trimestre"] = hist["data_pedido"].dt.to_period("Q").astype(str)
    oot = hist.groupby("trimestre").agg(contratos=("id_pedido", "size"), calotes_observados=("calote_obs", "sum"),
                                        calotes_previstos=("pd_ate_corte", "sum")).reset_index()
    oot["no_treino"] = oot["trimestre"] < "2025Q4"
    fora = hist[hist["data_pedido"] >= corte]
    auc_oot = roc_auc_score(fora["calote_obs"], fora["pd_ate_corte"])
    log.info("AUC fora do tempo: %.3f", auc_oot)

    # 2/3. backtest cross-fitted
    configs = {"proposta": Parametros(), "margem 0%": Parametros(margem_min=0.0),
               "margem 3%": Parametros(margem_min=0.03), "teto 30% da sobra": Parametros(teto_parcela_sobre_sobra=0.30),
               "teto 50% da sobra": Parametros(teto_parcela_sobre_sobra=0.50)}
    fold = np.random.RandomState(0).randint(0, n_folds, len(hb))
    res = []
    for f in range(n_folds):
        tr = hist[~hist["id_pedido"].isin(hb["id_pedido"][fold == f])]
        mf = ModeloEnsemble(seeds=(11, 22, 33)).fit(tr, d["parcelas"])
        te = hb[fold == f].reset_index(drop=True)
        for nome, p in configs.items():
            dn = politica_nova(te, mf, L, p)
            dn["ev"] = resultado_esperado(dn, te, mf, L).values
            res.append(dn.assign(cfg=nome))
        da = politica_atual(te).reset_index(drop=True)
        da["ev"] = resultado_esperado(da, te, mf, L).values
        res.append(da.assign(cfg="atual"))
        log.info("fold %d ok (%.0fs)", f, time.time() - t0)
    R = pd.concat(res)
    tab = R.groupby("cfg").agg(aprovados=("decisao", lambda x: int((x == "APROVADO").sum())),
                               valor=("valor_aprovado", "sum"), resultado=("ev", "sum")).reset_index()
    tab["ganho_vs_atual"] = tab["resultado"] - float(tab.loc[tab["cfg"] == "atual", "resultado"].iloc[0])

    out = {
        "fora_do_tempo": {"treino_ate": corte, "auc": round(float(auc_oot), 3), "por_trimestre": oot.to_dict("records")},
        "backtest": tab.to_dict("records"),
        "n_pedidos": int(len(hb)),
        "duracao_s": round(time.time() - t0, 1),
    }
    (RAIZ / "output" / "avaliacao.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    log.info("ok: %s", tab.round(0).to_string())


if __name__ == "__main__":
    main()
