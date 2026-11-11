"""Modelo de risco de calote ciente da censura (hazard em tempo discreto, por parcela).

Cada contrato aprovado do histórico vira uma linha por parcela *observável* (vencida há >60 dias na
data de corte), até a parcela em que deu calote. O modelo aprende h(k) = P(calote começa na parcela k |
pagou até k-1). A chance de calote no contrato inteiro é PD = 1 - prod_k (1 - h(k)), k = 1..prazo.

Assim um contrato "em dia há 1 mês" contribui só com 1 parcela de evidência, e não como bom pagador.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import lightgbm as lgb

from features import features_do_valor
from target import DATA_CORTE, DIAS_CALOTE

# features do cliente (não dependem do valor). Fora de propósito: gênero, CEP, estado civil, idade
# (não discriminam e não são defensáveis numa política de crédito) e campos de desfecho/política.
FEATS_CLIENTE = [
    "score", "restricoes_ativas", "parcelas_outras_instituicoes", "consultas_90_dias", "meses_historico_bureau",
    "renda_declarada", "meses_conta", "prazo_meses",
    "mov_meses", "mov_entradas_med", "mov_entradas_cv", "mov_salario_med", "mov_frac_meses_salario",
    "mov_saldo_medio_med", "mov_saldo_minimo_min", "mov_dias_cheque_total", "mov_meses_cheque",
    "mov_dias_cheque_ult3", "mov_entradas_ult3", "mov_saldo_medio_ult3", "mov_saidas_sobre_entradas",
    "mov_tendencia_entradas", "mov_frac_salario_nas_entradas", "renda_decl_sobre_real",
    "divida_outras_sobre_renda", "vinc_aposentado", "vinc_assalariado", "vinc_autonomo", "vinc_empresario",
]
# features que dependem do valor concedido: risco só pode subir com o valor (monotonicidade)
FEATS_VALOR = ["comprometimento", "comprometimento_total", "comprometimento_real", "parcela_sobre_sobra"]
FEAT_TEMPO = ["t_rel"]
FEATS = FEATS_CLIENTE + FEATS_VALOR + FEAT_TEMPO

PARAMS = dict(objective="binary", learning_rate=0.03, num_leaves=15, min_child_samples=80,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, seed=42)


def preparar_cliente(base: pd.DataFrame) -> pd.DataFrame:
    X = base.copy()
    for v in ["aposentado", "assalariado", "autonomo", "empresario"]:
        X[f"vinc_{v}"] = (X["tipo_vinculo"] == v).astype(int)
    return X


def feats_valor(base: pd.DataFrame, valor) -> pd.DataFrame:
    fv = features_do_valor(base, valor)
    sobra = (base["mov_entradas_med"] - base["mov_saidas_med"]).clip(lower=1).values
    fv["parcela_sobre_sobra"] = fv["parcela"].values / sobra
    return fv


def tabela_pessoa_parcela(hist: pd.DataFrame, parcelas: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (contrato, parcela observável) até o calote."""
    pa = parcelas.copy()
    pa["observavel"] = pa["data_vencimento"] <= DATA_CORTE - pd.Timedelta(days=DIAS_CALOTE + 1)
    pa["calote"] = pa["data_pagamento"].isna() & (pa["dias_atraso"] > DIAS_CALOTE)
    primeiro = pa[pa["calote"]].groupby("id_pedido")["numero_parcela"].min().rename("k_calote")
    pa = pa[pa["observavel"]].merge(primeiro, left_on="id_pedido", right_index=True, how="left")
    pa = pa[pa["k_calote"].isna() | (pa["numero_parcela"] <= pa["k_calote"])]
    pa["evento"] = (pa["numero_parcela"] == pa["k_calote"]).astype(int)
    pp = pa[["id_pedido", "numero_parcela", "evento"]].merge(hist, on="id_pedido", how="inner")
    pp["t_rel"] = pp["numero_parcela"] / pp["prazo_meses"]
    return pp


class ModeloCalote:
    def __init__(self, n_rounds: int = 400):
        self.n_rounds = n_rounds
        self.booster: lgb.Booster | None = None

    def _matriz(self, X: pd.DataFrame) -> pd.DataFrame:
        return X[FEATS].astype(float)

    def fit(self, hist: pd.DataFrame, parcelas: pd.DataFrame):
        """hist: base dos aprovados históricos (com valor_aprovado)."""
        h = preparar_cliente(hist).drop(columns=FEATS_VALOR + ["valor", "parcela"], errors="ignore")
        h = pd.concat([h, feats_valor(h, h["valor_aprovado"]).drop(columns=["valor", "parcela"])], axis=1)
        pp = tabela_pessoa_parcela(h, parcelas)
        mono = [1 if f in FEATS_VALOR else 0 for f in FEATS]
        ds = lgb.Dataset(self._matriz(pp), label=pp["evento"], free_raw_data=False)
        self.booster = lgb.train({**PARAMS, "monotone_constraints": mono, "monotone_constraints_method": "advanced"},
                                 ds, num_boost_round=self.n_rounds)
        self.n_linhas_treino, self.n_eventos = len(pp), int(pp["evento"].sum())
        return self

    def pd_contrato(self, base: pd.DataFrame, valor, ate_parcela=None) -> np.ndarray:
        """PD do contrato inteiro (ou até `ate_parcela`) para o valor dado. Vetorizado por prazo."""
        X = preparar_cliente(base).drop(columns=FEATS_VALOR + ["valor", "parcela"], errors="ignore").reset_index(drop=True)
        fv = feats_valor(X, np.asarray(valor, float)).drop(columns=["valor", "parcela"])
        X = pd.concat([X, fv.reset_index(drop=True)], axis=1)
        prazo = X["prazo_meses"].astype(int).values
        lim = prazo if ate_parcela is None else np.minimum(prazo, np.asarray(ate_parcela, int))
        kmax = int(lim.max()) if len(lim) else 0
        log_sobrev = np.zeros(len(X))
        for k in range(1, kmax + 1):
            ativos = lim >= k
            if not ativos.any():
                continue
            Xk = X.loc[ativos].copy()
            Xk["t_rel"] = k / Xk["prazo_meses"]
            hk = self.booster.predict(self._matriz(Xk))
            log_sobrev[ativos] += np.log1p(-np.clip(hk, 0, 0.999999))
        return 1 - np.exp(log_sobrev)

    def importancia(self) -> pd.Series:
        return pd.Series(self.booster.feature_importance("gain"), index=FEATS).sort_values(ascending=False)


def km_relativo(df: pd.DataFrame, n_bins: int = 10) -> tuple[float, float]:
    """Kaplan-Meier em tempo relativo (parcela / janela de risco), para taxas de calote de um grupo.

    df precisa de: k_evento (parcela do calote ou NaN), n_observaveis, prazo_meses.
    Retorna (PD estimada no contrato inteiro, n).
    """
    if len(df) == 0:
        return np.nan, 0
    janela = np.ceil(0.6 * df["prazo_meses"].values)
    t_ev = np.minimum(df["k_evento"].values / janela, 1.0)  # NaN se não houve calote
    t_obs = np.minimum(df["n_observaveis"].values / janela, 1.0)
    bordas = np.linspace(0, 1, n_bins + 1)
    sobrev = 1.0
    for a, b in zip(bordas[:-1], bordas[1:]):
        # em risco: observado além de 'a' e sem calote antes de 'a'
        em_risco = (t_obs > a) & ~(t_ev <= a)
        eventos = em_risco & (t_ev > a) & (t_ev <= b + 1e-9)
        nr = em_risco.sum()
        if nr > 0:
            sobrev *= 1 - eventos.sum() / nr
    return 1 - sobrev, len(df)
