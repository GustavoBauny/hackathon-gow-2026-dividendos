"""Política atual (réplica) e política proposta, em passos auditáveis.

Resultado financeiro por pedido aprovado (regra do desafio):
  pagou em dia +15% | pagou com atraso +5% | não pagou -60% | negado 0
Resultado esperado por real emprestado:
  margem = (1-PD) x (0,15 x (1-L) + 0,05 x L) - 0,60 x PD
  PD = chance de calote no valor aprovado; L = chance de atrasar entre quem paga (modelo de risco)

As regras de negação são dados (`Regra`): a IA sugere, o analista liga/desliga e ajusta o limiar
no painel, e a versão aprovada fica gravada em `politica_aprovada.json` (lida pelo pipeline).
"""
from __future__ import annotations

import json
import operator
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from features import LIMIARES, VALOR_MAX, VALOR_MIN, valor_max_por_parcela

GANHO_EM_DIA, GANHO_ATRASO, PERDA_CALOTE = 0.15, 0.05, 0.60
_OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "==": operator.eq}


def margem_por_real(pd_, l_):
    return (1 - pd_) * (GANHO_EM_DIA * (1 - l_) + GANHO_ATRASO * l_) - PERDA_CALOTE * pd_


# ----------------------------------------------------------------------------------------------
# Política atual: score > 600, renda > 2.000, sem restrição; parcela até 30% da renda declarada.
# No histórico, quando a parcela passa de 30%, o valor é reduzido ao teto (não nega).
# Reproduz 100% das 8.737 decisões históricas da política atual.
# ----------------------------------------------------------------------------------------------
def politica_atual(base: pd.DataFrame) -> pd.DataFrame:
    elegivel = (base["score"] > 600) & (base["renda_declarada"] > 2000) & (base["restricoes_ativas"] == 0)
    teto = np.floor(valor_max_por_parcela(0.30 * base["renda_declarada"], base["prazo_meses"]) * 100) / 100
    valor = np.minimum(np.minimum(base["valor_solicitado"], teto), VALOR_MAX)
    aprova = elegivel & (valor > 0)
    return pd.DataFrame({"id_pedido": base["id_pedido"].values,
                         "decisao": np.where(aprova, "APROVADO", "NEGADO"),
                         "valor_aprovado": np.where(aprova, valor, 0.0).round(2)}, index=base.index)


# ----------------------------------------------------------------------------------------------
# Política proposta
# ----------------------------------------------------------------------------------------------
@dataclass
class Regra:
    """Regra de negação: nega quando `coluna <op> limiar`. Valor ausente nunca nega."""
    id: str
    passo: int                 # 2 = fora da faixa com evidência, 3 = sinal de alerta
    coluna: str
    op: str
    limiar: float
    motivo: str                # texto de negócio; pode usar {limiar}
    ativa: bool = True
    padrao: str = ""           # id do padrão (painel, aba 1) que justifica a regra

    def mascara(self, b: pd.DataFrame) -> np.ndarray:
        x = pd.to_numeric(b[self.coluna], errors="coerce")
        return _OPS[self.op](x, self.limiar).fillna(False).to_numpy(bool)

    def texto(self) -> str:
        lim = float(self.limiar)
        return self.motivo.format(limiar=int(lim) if lim.is_integer() else lim)


def regras_padrao() -> list[Regra]:
    L = LIMIARES
    return [
        # Passo 2: fora da faixa que o piloto testou -> nega (sem evidência de pagamento, sem aposta)
        Regra("restricoes", 2, "restricoes_ativas", ">=", 2,
              "{limiar} ou mais restrições ativas no bureau (nunca aprovado no histórico)", padrao="P08"),
        Regra("score_min", 2, "score", "<=", 450, "score do bureau até {limiar} (nunca aprovado no histórico)", padrao="P06"),
        Regra("renda_min", 2, "renda_declarada", "<=", 1500, "renda declarada até R$ {limiar} (nunca aprovada no histórico)",
              padrao="P09"),
        # Passo 3: sinais de alerta descobertos pela IA no histórico
        Regra("gasta_tudo", 3, "mov_saidas_sobre_entradas", ">=", L["saidas_sobre_entradas"],
              "saídas da conta chegam a {limiar:.0%} ou mais das entradas", padrao="P02"),
        Regra("renda_inflada", 3, "renda_decl_sobre_real", ">", L["renda_inflada"],
              "renda declarada mais de {limiar}x o que entra na conta", padrao="P03"),
        Regra("pedido_excessivo", 3, "pedido_sobre_entradas", ">", L["pedido_sobre_entradas"],
              "pede mais de {limiar}x o que entra por mês na conta", padrao="P04"),
        Regra("divida_alta", 3, "outras_sobre_entradas", ">", L["outras_sobre_entradas"],
              "parcelas em outras instituições acima de {limiar:.0%} das entradas", padrao="P05"),
        Regra("entradas_instaveis", 3, "mov_entradas_cv", ">", L["cv_entradas"],
              "entradas mensais instáveis (variação acima de {limiar:.0%})", padrao="P07"),
    ]


@dataclass
class Parametros:
    regras: list[Regra] = field(default_factory=regras_padrao)
    # Passo 4: teto de valor pela capacidade de pagamento (None desliga o teto)
    teto_parcela_sobre_sobra: float | None = 0.45   # calote é certo acima de 50% da sobra: folga de 5 p.p.
    teto_comprometimento: float | None = 0.30       # trava de segurança: o histórico nunca passou de 35%
    # Passo 5: risco x retorno
    usar_modelo: bool = True
    margem_min: float = 0.01          # resultado esperado mínimo por real emprestado (folga para erro do modelo)

    def regra(self, id_: str) -> Regra:
        return next(r for r in self.regras if r.id == id_)


def parametros_dict(p: Parametros) -> dict:
    return asdict(p)


def parametros_de_dict(d: dict) -> Parametros:
    d = dict(d)
    regras = [Regra(**r) for r in d.pop("regras", [])] or regras_padrao()
    return Parametros(regras=regras, **{k: v for k, v in d.items() if k in Parametros.__dataclass_fields__})


def carregar_parametros(caminho: str | Path) -> Parametros:
    caminho = Path(caminho)
    if not caminho.exists():
        return Parametros()
    return parametros_de_dict(json.loads(caminho.read_text(encoding="utf-8"))["parametros"])


PASSOS = {
    1: "1. Dados do bureau",
    2: "2. Fora da faixa com evidência",
    3: "3. Sinal de alerta",
    4: "4. Capacidade de pagamento",
    5: "5. Risco x retorno",
    6: "6. Aprovado",
}


def teto_capacidade(b: pd.DataFrame, p: Parametros) -> np.ndarray:
    n = len(b)
    sobra = b["sobra"].clip(lower=0).fillna(0).to_numpy(float)
    # trava fixa: acima de 50% da sobra o calote é certo (P01); nenhum ajuste do analista passa disso.
    # A parcela máxima é arredondada para baixo no centavo, para a parcela Price (arredondada) não estourar.
    parcela_trava = np.floor(np.round(LIMIARES["parcela_sobre_sobra"] * sobra * 100, 6)) / 100
    limites = [b["valor_solicitado"].to_numpy(float), np.full(n, VALOR_MAX),
               valor_max_por_parcela(parcela_trava, b["prazo_meses"])]
    if p.teto_parcela_sobre_sobra is not None:
        limites.append(valor_max_por_parcela(p.teto_parcela_sobre_sobra * sobra, b["prazo_meses"]))
    if p.teto_comprometimento is not None:
        limites.append(valor_max_por_parcela(p.teto_comprometimento * b["renda_declarada"], b["prazo_meses"]))
    return np.floor(np.minimum.reduce(limites) * 100) / 100


def politica_nova(base: pd.DataFrame, modelo, p: Parametros | None = None) -> pd.DataFrame:
    """Aplica a política proposta. `modelo`: risco.ModeloRisco ajustado no histórico."""
    p = p or Parametros()
    b = base.reset_index(drop=True)
    n = len(b)
    out = pd.DataFrame({"id_pedido": b["id_pedido"], "decisao": "NEGADO", "valor_aprovado": 0.0,
                        "passo": 0, "regra": "", "motivo": "", "valor_teto": np.nan,
                        "pd": np.nan, "p_atraso": np.nan, "margem": np.nan})
    aberto = np.ones(n, bool)

    def negar(mask, passo, regra, motivo):
        nonlocal aberto
        m = aberto & np.asarray(mask, bool)
        out.loc[m, ["passo", "regra", "motivo"]] = [passo, regra, motivo]
        aberto = aberto & ~m

    # 1. bureau indisponível depois de todas as tentativas -> nega (conservador) e registra
    negar(b["score"].isna().to_numpy(), 1, "bureau", "bureau indisponível após todas as tentativas")

    # 2 e 3. regras de negação (fora da faixa e sinais de alerta), na ordem dos passos
    for r in sorted(p.regras, key=lambda r: r.passo):
        if r.ativa:
            negar(r.mascara(b), r.passo, r.id, r.texto())

    # 4. teto de valor pela capacidade de pagamento
    teto = teto_capacidade(b, p)
    out["valor_teto"] = teto
    negar(teto < VALOR_MIN, 4, "capacidade", "sobra mensal não comporta nem a parcela do valor mínimo (R$ 500)")

    # 5. risco x retorno no valor máximo permitido (o risco só depende do valor pela regra da sobra,
    #    já respeitada no teto, então o maior valor seguro é também o de maior resultado esperado)
    pd_ = modelo.pd_total(b, teto)
    la = modelo.p_atraso(b)
    mg = margem_por_real(pd_, la)
    out["pd"], out["p_atraso"], out["margem"] = pd_, la, mg
    if p.usar_modelo:
        negar(mg < p.margem_min, 5, "risco", "resultado esperado negativo: chance de calote alta demais")

    # 6. aprova no teto
    ap = np.where(aberto)[0]
    out.loc[ap, "decisao"] = "APROVADO"
    out.loc[ap, "valor_aprovado"] = teto[ap]
    out.loc[ap, ["passo", "regra"]] = [6, "aprovado"]
    sol = b.loc[ap, "valor_solicitado"].to_numpy(float)
    out.loc[ap, "motivo"] = np.where(teto[ap] < sol - 0.005, "aprovado com valor reduzido", "aprovado no valor pedido")
    out["valor_aprovado"] = out["valor_aprovado"].round(2)
    return out


def resultado_esperado(decisoes: pd.DataFrame, base: pd.DataFrame, modelo) -> pd.Series:
    """Resultado esperado de cada decisão segundo o modelo de risco (compara políticas nos mesmos pedidos)."""
    b = base.reset_index(drop=True)
    v = decisoes["valor_aprovado"].to_numpy(float)
    ev = np.zeros(len(b))
    m = v > 0
    if m.any():
        bm = b[m]
        ev[m] = v[m] * margem_por_real(modelo.pd_total(bm, v[m]), modelo.p_atraso(bm))
    return pd.Series(ev, index=decisoes.index)
