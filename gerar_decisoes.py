"""Gera o arquivo de decisões do zero.

banco (PostgreSQL) -> alvo com censura -> modelo de calote (hazard + calibração) -> API do bureau
-> política proposta -> output/dividendos_final.csv (validado) + artefatos do painel.

Uso:  python gerar_decisoes.py            (precisa de FORTUNA_BUREAU_TOKEN ou solucao/.bureau_token)
      python gerar_decisoes.py --so-cache  (não chama a API; usa só o cache do bureau)
"""
from __future__ import annotations

import argparse
import json
import logging
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "src"))

from db import carregar  # noqa: E402
from features import montar_base  # noqa: E402
from target import construir_alvo  # noqa: E402
from modelo import ModeloEnsemble, km_relativo  # noqa: E402
from politica import (Parametros, politica_atual, politica_nova, resultado_esperado,  # noqa: E402
                      taxa_atraso_por_segmento, parametros_dict, PASSOS)
from bureau_client import BureauClient, TokenInvalido  # noqa: E402
import padroes  # noqa: E402

TIME = "dividendos"
SAIDA = RAIZ / "output"
DADOS = RAIZ / "data"
CAMPOS_BUREAU = ["score", "restricoes_ativas", "parcelas_outras_instituicoes", "consultas_90_dias", "meses_historico_bureau"]

log = logging.getLogger("pipeline")


def escrever_csv(dec: pd.DataFrame, caminho: Path):
    """UTF-8 sem BOM, vírgula, ponto decimal com 2 casas, LF. Gerado pelo código, nunca editado à mão."""
    linhas = ["id_pedido,decisao,valor_aprovado"]
    for r in dec.itertuples(index=False):
        valor = r.valor_aprovado if r.decisao == "APROVADO" else 0.0
        linhas.append(f"{r.id_pedido},{r.decisao},{valor:.2f}")
    caminho.write_bytes(("\n".join(linhas) + "\n").encode("utf-8"))


def validar_csv(caminho: Path, novos: pd.DataFrame) -> dict:
    """Confere o arquivo contra as regras do manual (seção 5.2)."""
    raw = caminho.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "arquivo com BOM"
    texto = raw.decode("utf-8")
    linhas = texto.strip("\n").split("\n")
    assert linhas[0] == "id_pedido,decisao,valor_aprovado", f"cabeçalho inválido: {linhas[0]!r}"
    df = pd.read_csv(caminho, dtype=str)
    sol = novos.set_index("id_pedido")["valor_solicitado"]
    assert df["id_pedido"].is_unique, "id_pedido repetido"
    assert set(df["id_pedido"]) == set(novos["id_pedido"]), "conjunto de pedidos difere da base de novos"
    assert df["decisao"].isin(["APROVADO", "NEGADO"]).all(), "decisao fora de APROVADO/NEGADO"
    assert df["valor_aprovado"].str.fullmatch(r"\d+\.\d{2}").all(), "valor fora do formato 0.00"
    v = df["valor_aprovado"].astype(float)
    ap = df["decisao"] == "APROVADO"
    assert (v[~ap] == 0).all(), "negado com valor diferente de 0.00"
    assert (v[ap] >= 500).all(), "aprovado abaixo do mínimo do produto (R$ 500)"
    assert (v[ap] <= 30000).all(), "aprovado acima de R$ 30 mil"
    assert (v[ap].values <= df.loc[ap, "id_pedido"].map(sol).values + 1e-9).all(), "aprovado acima do solicitado"
    return {"linhas": len(df), "aprovados": int(ap.sum()), "negados": int((~ap).sum()),
            "valor_total_aprovado": round(float(v.sum()), 2)}


def buscar_bureau(ids_clientes: list[str], so_cache: bool) -> tuple[pd.DataFrame, dict]:
    cache = DADOS / "bureau_cache.jsonl"
    if so_cache:
        cli = BureauClient.__new__(BureauClient)
        cli.cache_path = cache
        regs = [r for r in BureauClient._carregar_cache(cli).values() if r["id_cliente"] in set(ids_clientes)]
        stats = {"modo": "so_cache", "clientes_no_cache": len(regs)}
    else:
        cli = BureauClient(cache_path=cache)
        t0 = time.time()
        regs = cli.consultar_lote(ids_clientes)
        stats = {"modo": "api", "duracao_s": round(time.time() - t0, 1), **cli.stats.resumo()}
    df = pd.DataFrame(regs)
    if len(df) == 0:
        df = pd.DataFrame(columns=["id_cliente", "status"] + CAMPOS_BUREAU)
    ok = df[df["status"] == "ok"]
    stats.update({"clientes": len(ids_clientes), "com_dados": int(len(ok)),
                  "sem_dados": int(len(ids_clientes) - len(ok)),
                  "tentativas_media": round(float(ok["tentativas"].mean()), 2) if "tentativas" in ok and len(ok) else None,
                  "tentativas_max": int(ok["tentativas"].max()) if "tentativas" in ok and len(ok) else None})
    return ok[["id_cliente"] + CAMPOS_BUREAU], stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--so-cache", action="store_true", help="não chama a API do bureau; usa só o cache")
    ap.add_argument("--saida", default=str(SAIDA / f"{TIME}_final.csv"))
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    SAIDA.mkdir(exist_ok=True)
    DADOS.mkdir(exist_ok=True)
    t0 = time.time()

    # 1. dados
    log.info("carregando banco")
    d = carregar()
    alvo = construir_alvo(d["pedidos"], d["parcelas"])
    base_hist = montar_base(d)
    hist = base_hist.merge(alvo[["id_pedido", "n_observaveis", "calote_obs", "k_evento", "exposicao",
                                 "frac_vencida", "atraso_obs", "maduro"]], on="id_pedido")
    log.info("histórico aprovado: %d contratos, %d calotes observados", len(hist), int(hist["calote_obs"].sum()))

    # 2. modelo
    log.info("treinando ensemble de 5 modelos de calote (hazard por parcela), cada um calibrado fora da amostra")
    modelo = ModeloEnsemble().fit(hist, d["parcelas"])
    taxa_atraso = taxa_atraso_por_segmento(hist)
    with open(DADOS / "modelo.pkl", "wb") as f:
        pickle.dump({"modelo": modelo, "taxa_atraso": taxa_atraso}, f)

    # 3. bureau dos novos
    novos_ped = d["pedidos"][d["pedidos"]["tipo_base"] == "novo"]
    log.info("consultando bureau de %d clientes novos", len(novos_ped))
    bureau_novos, stats_bureau = buscar_bureau(novos_ped["id_cliente"].tolist(), args.so_cache)
    log.info("bureau: %s", stats_bureau)
    stats_api_path = SAIDA / "bureau_execucao_api.json"
    if stats_bureau.get("chamadas_http"):  # guarda a última execução que de fato chamou a API
        stats_api_path.write_text(json.dumps({**stats_bureau, "registrado_em": time.strftime("%Y-%m-%d %H:%M:%S")},
                                             ensure_ascii=False, indent=2), encoding="utf-8")
    stats_api = json.loads(stats_api_path.read_text(encoding="utf-8")) if stats_api_path.exists() else stats_bureau
    base = montar_base(d, bureau_novos)
    novos = base[base["tipo_base"] == "novo"].sort_values("id_pedido").reset_index(drop=True)

    # 4. decisões
    params = Parametros()
    dec = politica_nova(novos, modelo, taxa_atraso, params)
    atual = politica_atual(novos).reset_index(drop=True)
    tem_bureau = novos["score"].notna().values
    atual.loc[~tem_bureau, ["decisao", "valor_aprovado"]] = ["NEGADO", 0.0]  # sem bureau a atual também não decide
    dec["ev_modelo"] = resultado_esperado(dec, novos, modelo, taxa_atraso).values
    atual["ev_modelo"] = resultado_esperado(atual, novos, modelo, taxa_atraso).values

    # 5. arquivo final
    saida = Path(args.saida)
    escrever_csv(dec[["id_pedido", "decisao", "valor_aprovado"]], saida)
    val = validar_csv(saida, novos)
    log.info("CSV válido: %s -> %s", val, saida)

    # 6. artefatos para painel / auditoria
    det = novos[["id_pedido", "id_cliente", "valor_solicitado", "prazo_meses", "renda_declarada", "tipo_vinculo",
                 "score", "restricoes_ativas", "consultas_90_dias", "parcelas_outras_instituicoes",
                 "mov_entradas_med", "mov_saidas_med", "mov_meses_cheque", "mov_saidas_sobre_entradas",
                 "renda_decl_sobre_real", "mov_entradas_cv"]].copy()
    det = det.merge(dec, on="id_pedido").merge(
        atual.rename(columns={"decisao": "decisao_atual", "valor_aprovado": "valor_atual", "ev_modelo": "ev_atual"}),
        on="id_pedido")
    det["passo_nome"] = det["passo"].map(PASSOS)
    det.to_csv(SAIDA / "decisoes_detalhadas.csv", index=False, encoding="utf-8", float_format="%.4f")

    det["grupo"] = np.select(
        [(det.decisao_atual == "APROVADO") & (det.decisao == "NEGADO"),
         (det.decisao_atual == "NEGADO") & (det.decisao == "APROVADO"),
         (det.decisao_atual == "APROVADO") & (det.decisao == "APROVADO") & (det.valor_aprovado < det.valor_atual - 1),
         (det.decisao_atual == "APROVADO") & (det.decisao == "APROVADO")],
        ["A atual aprova, a proposta nega", "A atual nega, a proposta aprova",
         "As duas aprovam, a proposta reduz o valor", "As duas aprovam o mesmo valor (ou maior)"], "As duas negam")
    decomp = det.groupby("grupo").agg(pedidos=("id_pedido", "size"), valor_atual=("valor_atual", "sum"),
                                      valor_proposta=("valor_aprovado", "sum"), ev_atual=("ev_atual", "sum"),
                                      ev_proposta=("ev_modelo", "sum")).reset_index()
    decomp["ganho"] = decomp["ev_proposta"] - decomp["ev_atual"]

    h = padroes.preparar(hist)
    lista, ref = padroes.padroes_negocio(h, novos)
    resumo = {
        "gerado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duracao_s": round(time.time() - t0, 1),
        "csv": {"arquivo": saida.name, **val},
        "diferencas_vs_atual": int((det["decisao"] != det["decisao_atual"]).sum()),
        "atual": {"aprovados": int((atual.decisao == "APROVADO").sum()), "valor": float(atual.valor_aprovado.sum()),
                  "ev_modelo": float(atual.ev_modelo.sum())},
        "proposta": {"aprovados": int((dec.decisao == "APROVADO").sum()), "valor": float(dec.valor_aprovado.sum()),
                     "ev_modelo": float(dec.ev_modelo.sum()),
                     "reduzidos": int((det.motivo == "aprovado com valor reduzido").sum())},
        "ganho_estimado": float(dec.ev_modelo.sum() - atual.ev_modelo.sum()),
        "decomposicao": decomp.to_dict("records"),
        "por_passo": det.groupby(["passo", "passo_nome", "motivo"]).size().rename("pedidos").reset_index().to_dict("records"),
        "bureau": stats_bureau,
        "bureau_api": stats_api,
        "parametros": parametros_dict(params),
        "taxa_atraso": taxa_atraso,
        "modelo": {
            "linhas_treino": modelo.n_linhas_treino, "eventos": modelo.n_eventos,
            "features": modelo.feats,
            "importancia": modelo.importancia().round(1).to_dict(),
            "calibracao": modelo.tabela_calibracao.round(4).reset_index().to_dict("records"),
        },
        "alvo": {
            "contratos_aprovados": len(hist), "calotes_observados": int(hist["calote_obs"].sum()),
            "taxa_ingenua": float(hist["calote_obs"].mean()), "taxa_km": float(km_relativo(hist)[0]),
            "maduros": int(hist["maduro"].sum()),
        },
        "padroes": lista, "padroes_ref": ref,
        "varredura": padroes.varredura_univariada(h).to_dict("records"),
        "arvore": padroes.arvore_combinacoes(h).to_dict("records"),
        "onde_atual_erra": padroes.onde_a_politica_atual_erra(h),
    }
    (SAIDA / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    log.info("aprovados: proposta %d (R$ %.0f) | atual %d (R$ %.0f) | ganho estimado R$ %.0f | %.0fs",
             resumo["proposta"]["aprovados"], resumo["proposta"]["valor"], resumo["atual"]["aprovados"],
             resumo["atual"]["valor"], resumo["ganho_estimado"], time.time() - t0)

    try:
        from gerar_painel import gerar
        gerar(SAIDA / "resumo.json", SAIDA / "painel.html")
        log.info("painel: %s", SAIDA / "painel.html")
    except ImportError:
        pass


if __name__ == "__main__":
    try:
        main()
    except TokenInvalido as e:
        sys.exit(f"ERRO: {e}")
