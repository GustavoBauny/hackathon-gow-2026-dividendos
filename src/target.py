"""Construção do alvo com tratamento de contratos em andamento (censura).

Fatos medidos no histórico (ver painel):
  * atraso de parcela paga nunca passa de 60 dias -> parcela vencida e não paga há >60 dias = calote;
  * a 1ª parcela não paga dos inadimplentes cai de forma ~uniforme entre a parcela 1 e ceil(0,6 x prazo).

Logo, um contrato que ainda não deu calote só "provou" ser bom pagador na fração da janela de risco
que já foi observada. `exposicao` = fração da janela de risco já observada (0 a 1).
"""
import numpy as np
import pandas as pd

DATA_CORTE = pd.Timestamp("2026-09-30")
DIAS_CALOTE = 60          # acima disso, parcela não paga é calote (atraso pago máximo = 60 dias)
FRACAO_JANELA = 0.6       # calote começa até ceil(0,6 x prazo)


def construir_alvo(pedidos: pd.DataFrame, parcelas: pd.DataFrame) -> pd.DataFrame:
    ap = pedidos[(pedidos["tipo_base"] == "historico") & (pedidos["decisao"] == "aprovado")][
        ["id_pedido", "prazo_meses", "valor_aprovado", "situacao_final"]].copy()

    pa = parcelas.copy()
    pa["vencida"] = pa["data_vencimento"] <= DATA_CORTE
    pa["nao_paga"] = pa["data_pagamento"].isna() & pa["vencida"]
    pa["calote"] = pa["nao_paga"] & (pa["dias_atraso"] > DIAS_CALOTE)
    pa["atraso"] = pa["dias_atraso"].fillna(0) > 0
    # parcela "observável para calote": venceu há mais de 60 dias na data de corte
    pa["observavel"] = pa["data_vencimento"] <= DATA_CORTE - pd.Timedelta(days=DIAS_CALOTE + 1)

    g = pa.groupby("id_pedido")
    agg = pd.DataFrame({
        "n_vencidas": g["vencida"].sum(),
        "n_observaveis": g["observavel"].sum(),
        "calote_obs": g["calote"].any(),
        "atraso_obs": g["atraso"].any(),
        "n_parcelas_atraso": g["atraso"].sum(),
        "k_evento": pa[pa["calote"]].groupby("id_pedido")["numero_parcela"].min(),
    })
    ap = ap.merge(agg, left_on="id_pedido", right_index=True, how="left")
    janela = np.ceil(FRACAO_JANELA * ap["prazo_meses"])
    # exposição pelo calendário (vale para todos, inclusive quem já deu calote):
    # probabilidade de um futuro inadimplente já ter sido detectado na data de corte
    ap["exposicao"] = np.clip(ap["n_observaveis"] / janela, 0, 1)
    ap["maduro"] = ap["exposicao"] >= 1.0
    # fração do contrato já vencida (para o alvo de atraso)
    ap["frac_vencida"] = ap["n_vencidas"] / ap["prazo_meses"]
    return ap


def taxa_calote_ajustada(calote_obs: pd.Series, exposicao: pd.Series) -> float:
    """Estimador por exposição: E[calote_obs] = p x exposicao  =>  p = sum(calote) / sum(exposicao)."""
    e = exposicao.sum()
    return float(calote_obs.sum() / e) if e > 0 else np.nan


def posterior_calote(p: np.ndarray, exposicao: np.ndarray, calote_obs: np.ndarray) -> np.ndarray:
    """P(vai dar calote | ainda não deu, viu fração `exposicao` da janela) = p(1-F)/(1-pF)."""
    p = np.clip(p, 1e-6, 1 - 1e-6)
    q = p * (1 - exposicao) / (1 - p * exposicao)
    return np.where(calote_obs, 1.0, q)
