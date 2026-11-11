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
FEATS_TODAS = FEATS_CLIENTE + FEATS_VALOR + FEAT_TEMPO
# conjunto enxuto escolhido por validação cruzada (AUC 0,836 / log-loss 0,231 fora da amostra, contra
# 0,826 / 0,238 com todas as features): menos ruído e mais fácil de explicar ao analista.
FEATS = ["score", "restricoes_ativas", "consultas_90_dias", "meses_historico_bureau", "divida_outras_sobre_renda",
         "renda_declarada", "prazo_meses", "mov_entradas_cv", "mov_saldo_medio_med", "mov_meses_cheque",
         "mov_dias_cheque_total", "mov_saidas_sobre_entradas", "renda_decl_sobre_real",
         "vinc_aposentado", "vinc_assalariado", "vinc_autonomo", "vinc_empresario"] + FEATS_VALOR + FEAT_TEMPO

PARAMS = dict(objective="binary", learning_rate=0.03, num_leaves=4, min_child_samples=500,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, seed=42)
N_ROUNDS = 300


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
    def __init__(self, n_rounds: int = N_ROUNDS, params: dict | None = None, feats: list[str] | None = None):
        self.n_rounds = n_rounds
        self.params = {**PARAMS, **(params or {})}
        self.feats = list(feats or FEATS)
        self.booster: lgb.Booster | None = None
        self.calibrador = None  # (x_bordas, y_pd) da calibração isotônica

    def _matriz(self, X: pd.DataFrame) -> pd.DataFrame:
        return X[self.feats].astype(float)

    def fit(self, hist: pd.DataFrame, parcelas: pd.DataFrame):
        """hist: base dos aprovados históricos (com valor_aprovado)."""
        h = preparar_cliente(hist).drop(columns=FEATS_VALOR + ["valor", "parcela"], errors="ignore")
        h = pd.concat([h, feats_valor(h, h["valor_aprovado"]).drop(columns=["valor", "parcela"])], axis=1)
        pp = tabela_pessoa_parcela(h, parcelas)
        mono = [1 if f in FEATS_VALOR else 0 for f in self.feats]
        ds = lgb.Dataset(self._matriz(pp), label=pp["evento"], free_raw_data=False)
        self.booster = lgb.train({**self.params, "monotone_constraints": mono, "monotone_constraints_method": "advanced"},
                                 ds, num_boost_round=self.n_rounds)
        self.n_linhas_treino, self.n_eventos = len(pp), int(pp["evento"].sum())
        return self

    def pd_contrato(self, base: pd.DataFrame, valor, ate_parcela=None, calibrada: bool = True) -> np.ndarray:
        """PD do contrato inteiro para o valor dado (calibrada, se houver calibrador)."""
        bruta = self._pd_bruta(base, valor, ate_parcela)
        if calibrada and self.calibrador is not None and ate_parcela is None:
            x, y = self.calibrador
            return np.interp(bruta, x, y)
        return bruta

    def calibrar(self, hist: pd.DataFrame, parcelas: pd.DataFrame, n_folds: int = 5, n_faixas: int = 20, seed: int = 7):
        """Calibração isotônica fora da amostra: PD bruta (cross-fitted) -> Kaplan-Meier observado por faixa."""
        from sklearn.isotonic import IsotonicRegression
        h = hist.reset_index(drop=True)
        fold = np.random.RandomState(seed).randint(0, n_folds, len(h))
        oof = np.zeros(len(h))
        for f in range(n_folds):
            m = ModeloCalote(self.n_rounds, self.params, self.feats).fit(h[fold != f], parcelas)
            oof[fold == f] = m._pd_bruta(h[fold == f], h.loc[fold == f, "valor_aprovado"])
        h = h.assign(pd_bruta=oof, faixa=pd.qcut(oof, n_faixas, labels=False, duplicates="drop"))
        tab = h.groupby("faixa").apply(lambda g: pd.Series({
            "pd_bruta_media": g["pd_bruta"].mean(), "pd_km": km_relativo(g)[0], "n": len(g)}), include_groups=False)
        iso = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip")
        iso.fit(tab["pd_bruta_media"], tab["pd_km"], sample_weight=tab["n"])
        x = np.r_[0.0, tab["pd_bruta_media"].values, 1.0]
        y = np.r_[iso.predict([0.0])[0] if len(tab) else 0, iso.predict(tab["pd_bruta_media"]), 1.0]
        self.calibrador = (x, np.maximum.accumulate(y))
        tab["pd_calibrada"] = np.interp(tab["pd_bruta_media"], *self.calibrador)
        self.tabela_calibracao = tab
        self.oof = h[["id_pedido", "pd_bruta"]].assign(pd_calibrada=np.interp(oof, *self.calibrador))
        return self

    def _pd_bruta(self, base: pd.DataFrame, valor, ate_parcela=None) -> np.ndarray:
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
        return pd.Series(self.booster.feature_importance("gain"), index=self.feats).sort_values(ascending=False)


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
