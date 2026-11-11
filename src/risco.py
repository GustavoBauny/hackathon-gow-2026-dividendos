"""Modelo de risco explicável: risco base x fatores, ajustado no histórico levando em conta a censura.

Calote. Muitos contratos ainda estão em andamento: quem vai dar calote só aparece como calote se a
janela de risco já passou. Com exposição e = fração da janela já observada (target.py),
E[calote observado] = PD x e. Uma regressão de Poisson com log(e) como offset estima, então,
    PD = base x RR_1^{x_1} x RR_2^{x_2} x ...      (x_i = 1 se o fator está presente)
Cada RR é "quantas vezes o risco sobe (ou cai) com o fator", que é como o analista lê.
O ajuste usa os aprovados fora das três regras de calote certo, que entram à parte:
  * parcela acima de 50% da sobra mensal (ou sem sobra)  -> depende do valor aprovado
  * saídas iguais ou acima de 90% das entradas
  * renda declarada acima de 2x as entradas reais        -> taxa observada no histórico

Atraso. Entre quem não deu calote e já teve pelo menos metade do prazo vencido, uma logística estima
a chance de atrasar alguma parcela (vale +5% em vez de +15%).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

from features import LIMIARES, parcela_price

L = LIMIARES
FATORES_CALOTE = {
    "pedido_excessivo": (f"pede mais de {L['pedido_sobre_entradas']:.0f}x o que entra por mês na conta",
                         lambda b: b["pedido_sobre_entradas"] > L["pedido_sobre_entradas"]),
    "divida_alta": (f"parcelas em outras instituições acima de {L['outras_sobre_entradas']:.0%} das entradas",
                    lambda b: b["outras_sobre_entradas"] > L["outras_sobre_entradas"]),
    "entradas_instaveis": (f"entradas mensais instáveis (variação acima de {L['cv_entradas']:.0%})",
                           lambda b: b["mov_entradas_cv"] > L["cv_entradas"]),
    "aposentado": ("aposentado", lambda b: b["tipo_vinculo"] == "aposentado"),
    "bureau_curto": (f"menos de {L['bureau_curto_meses']} meses de histórico no bureau",
                     lambda b: b["meses_historico_bureau"] < L["bureau_curto_meses"]),
}
FATORES_ATRASO = {
    "divida_alta": FATORES_CALOTE["divida_alta"],
    "uma_restricao": ("1 restrição ativa no bureau", lambda b: b["restricoes_ativas"] == 1),
}


def _matriz(b: pd.DataFrame, fatores: dict) -> pd.DataFrame:
    return pd.DataFrame({k: f(b).fillna(False).astype(float).to_numpy() for k, (_, f) in fatores.items()}, index=b.index)


def regras_duras(b: pd.DataFrame, valor) -> dict[str, np.ndarray]:
    """Máscaras das três regras de calote certo, para o valor dado."""
    sobra = b["sobra"].to_numpy(float)
    parc = parcela_price(valor, b["prazo_meses"].to_numpy(float))
    with np.errstate(divide="ignore", invalid="ignore"):
        razao = np.where(sobra > 0, parc / sobra, np.inf)
    return {
        "capacidade": ~(razao <= L["parcela_sobre_sobra"]),  # inclui sem sobra e sem movimentação
        "saidas": (b["mov_saidas_sobre_entradas"] >= L["saidas_sobre_entradas"]).fillna(False).to_numpy(bool),
        "renda_inflada": (b["renda_decl_sobre_real"] > L["renda_inflada"]).fillna(False).to_numpy(bool),
    }


def _taxa(df: pd.DataFrame) -> float:
    e = df["exposicao"].sum()
    return float(min(1.0, df["calote_obs"].sum() / e)) if e > 0 else float("nan")


class ModeloRisco:
    def __init__(self):
        self.coef_calote: dict[str, float] = {}
        self.coef_atraso: dict[str, float] = {}
        self.taxas_duras: dict[str, float] = {}
        self.diagnostico: dict = {}

    # ------------------------------------------------------------------ ajuste
    def fit(self, hist_aprovados: pd.DataFrame) -> "ModeloRisco":
        a = hist_aprovados[hist_aprovados["exposicao"] > 0].copy()
        for c in ["calote_obs", "atraso_obs", "maduro"]:
            a[c] = a[c].astype(bool)
        duras = regras_duras(a, a["valor_aprovado"].to_numpy(float))
        cap, sai, inf = duras["capacidade"], duras["saidas"], duras["renda_inflada"]
        # (todo aprovado do perfil "saídas >= 90%" também estoura a capacidade, então a taxa é do grupo inteiro)
        self.taxas_duras = {"capacidade": _taxa(a[cap]), "saidas": _taxa(a[sai]),
                            "renda_inflada": _taxa(a[inf & ~sai & ~cap])}
        self.diagnostico["regras_duras"] = {
            k: {"aprovados": int(m.sum()), "calotes": int(a.loc[m, "calote_obs"].sum()),
                "maduros": int(a.loc[m, "maduro"].sum()), "calotes_maduros": int(a.loc[m & a["maduro"], "calote_obs"].sum())}
            for k, m in {"capacidade": cap, "saidas": sai, "renda_inflada": inf & ~sai & ~cap}.items()}

        limpo = a[~cap & ~sai & ~inf]
        X = sm.add_constant(_matriz(limpo, FATORES_CALOTE))
        glm = sm.GLM(limpo["calote_obs"].astype(float), X, family=sm.families.Poisson(),
                     offset=np.log(limpo["exposicao"])).fit()
        self.coef_calote = {k: float(v) for k, v in glm.params.items()}
        ic = glm.conf_int()
        self.diagnostico["calote"] = {
            "n_contratos": int(len(limpo)), "calotes": int(limpo["calote_obs"].sum()),
            "exposicao": round(float(limpo["exposicao"].sum()), 1), "aic": round(float(glm.aic), 1),
            "fatores": {k: {"rr": round(float(np.exp(glm.params[k])), 3), "p": float(glm.pvalues[k]),
                            "ic95": [round(float(np.exp(ic.loc[k, 0])), 3), round(float(np.exp(ic.loc[k, 1])), 3)]}
                        for k in glm.params.index},
        }

        nc = limpo[~limpo["calote_obs"] & (limpo["frac_vencida"] >= 0.5)]
        Xa = sm.add_constant(_matriz(nc, FATORES_ATRASO))
        lg = sm.Logit(nc["atraso_obs"].astype(float), Xa).fit(disp=0)
        self.coef_atraso = {k: float(v) for k, v in lg.params.items()}
        self.diagnostico["atraso"] = {
            "n_contratos": int(len(nc)), "taxa_base": round(float(1 / (1 + np.exp(-lg.params["const"]))), 4),
            "fatores": {k: {"odds_ratio": round(float(np.exp(lg.params[k])), 3), "p": float(lg.pvalues[k])}
                        for k in lg.params.index if k != "const"},
        }
        return self

    # ------------------------------------------------------------------ previsão
    def pd_base(self) -> float:
        return float(np.exp(self.coef_calote["const"]))

    def pd_fatores(self, b: pd.DataFrame) -> np.ndarray:
        """Chance de calote pelos fatores (sem as regras de calote certo)."""
        X = _matriz(b, FATORES_CALOTE)
        eta = self.coef_calote["const"] + X.to_numpy() @ np.array([self.coef_calote[k] for k in X.columns])
        return np.minimum(1.0, np.exp(eta))

    def pd_total(self, b: pd.DataFrame, valor) -> np.ndarray:
        """Chance de calote no valor dado, incluindo as regras de calote certo."""
        d = regras_duras(b, np.asarray(valor, float))
        p = self.pd_fatores(b)
        p = np.where(d["renda_inflada"], np.maximum(p, self.taxas_duras["renda_inflada"]), p)
        p = np.where(d["saidas"], np.maximum(p, self.taxas_duras["saidas"]), p)
        return np.where(d["capacidade"], np.maximum(p, self.taxas_duras["capacidade"]), p)

    def p_atraso(self, b: pd.DataFrame) -> np.ndarray:
        X = _matriz(b, FATORES_ATRASO)
        eta = self.coef_atraso["const"] + X.to_numpy() @ np.array([self.coef_atraso[k] for k in X.columns])
        return 1 / (1 + np.exp(-eta))

    def explicar(self, linha: pd.DataFrame) -> list[tuple[str, float]]:
        """Fatores presentes num pedido e o multiplicador de risco de cada um."""
        X = _matriz(linha, FATORES_CALOTE).iloc[0]
        return [(FATORES_CALOTE[k][0], float(np.exp(self.coef_calote[k]))) for k, v in X.items() if v]

    # ------------------------------------------------------------------ persistência
    def salvar(self, caminho) -> None:
        Path(caminho).write_text(json.dumps({"coef_calote": self.coef_calote, "coef_atraso": self.coef_atraso,
                                             "taxas_duras": self.taxas_duras, "diagnostico": self.diagnostico},
                                            ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def carregar(cls, caminho) -> "ModeloRisco":
        d = json.loads(Path(caminho).read_text(encoding="utf-8"))
        m = cls()
        m.coef_calote, m.coef_atraso, m.taxas_duras, m.diagnostico = (
            d["coef_calote"], d["coef_atraso"], d["taxas_duras"], d["diagnostico"])
        return m
