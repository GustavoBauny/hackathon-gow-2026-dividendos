"""Política atual (réplica) e política proposta, em passos auditáveis.

Resultado financeiro por pedido aprovado (regra do desafio):
  pagou em dia +15% | pagou com atraso +5% | não pagou -60% | negado 0
EV(valor) = valor x [ (1-PD) x (0,15 x (1-L) + 0,05 x L) - 0,60 x PD ]
  PD = chance de calote (modelo, depende do valor via comprometimento)
  L  = chance de atrasar alguma parcela entre quem paga (taxa histórica por segmento)
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from features import parcela_price, valor_max_por_parcela, VALOR_MIN, VALOR_MAX

GANHO_EM_DIA, GANHO_ATRASO, PERDA_CALOTE = 0.15, 0.05, 0.60


def margem_por_real(pd_, l_):
    return (1 - pd_) * (GANHO_EM_DIA * (1 - l_) + GANHO_ATRASO * l_) - PERDA_CALOTE * pd_


# ----------------------------------------------------------------------------------------------
# Política atual: score > 600, renda > 2.000, sem restrição; parcela até 30% da renda declarada.
# No histórico, quando a parcela passa de 30%, o valor é reduzido ao teto (não nega).
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
class Parametros:
    # Passo 2: fora da faixa onde o histórico tem desfecho -> nega (sem evidência, sem aposta)
    score_min: float = 450            # menor score aprovado no histórico: 452
    renda_min: float = 1500           # menor renda aprovada no histórico: 1.550
    restricoes_max: int = 1           # piloto aprovou até 1 restrição; 2+ nunca foi aprovado
    # Passo 3: sinais de alerta descobertos no histórico (calote de 70% a 100%)
    meses_cheque_max: int = 1         # 2+ meses no cheque especial nos últimos 12
    saidas_sobre_entradas_max: float = 0.80
    consultas_90d_max: int = 7        # 8+ consultas ao CPF em 90 dias
    renda_decl_sobre_real_max: float = 2.0
    # Passo 4: teto de valor pela capacidade de pagamento
    teto_parcela_sobre_sobra: float = 0.40   # calote salta para ~100% acima de 50% da sobra mensal
    teto_comprometimento: float = 0.30       # parcela / renda declarada (mesmo limite da política atual)
    # Passo 5/6: risco e valor
    margem_min: float = 0.01          # EV mínimo por real emprestado (folga para erro do modelo)
    pontos_grade: int = 24


PASSOS = {
    1: "Dados do bureau",
    2: "Fora da faixa com histórico",
    3: "Sinal de alerta",
    4: "Capacidade de pagamento",
    5: "Risco x retorno (modelo)",
    6: "Aprovado",
}


def taxa_atraso_por_segmento(hist_aprovados: pd.DataFrame) -> dict:
    """L = P(atrasar alguma parcela | não deu calote), em contratos com >=50% do prazo vencido."""
    s = hist_aprovados[(~hist_aprovados["calote_obs"]) & (hist_aprovados["frac_vencida"] >= 0.5)]
    sem = float(s.loc[s["restricoes_ativas"] == 0, "atraso_obs"].mean())
    com = float(s.loc[s["restricoes_ativas"] >= 1, "atraso_obs"].mean())
    return {"sem_restricao": round(sem, 4), "com_restricao": round(com, 4)}


def politica_nova(base: pd.DataFrame, modelo, taxa_atraso: dict, p: Parametros = Parametros()) -> pd.DataFrame:
    b = base.reset_index(drop=True)
    n = len(b)
    out = pd.DataFrame({"id_pedido": b["id_pedido"], "decisao": "NEGADO", "valor_aprovado": 0.0,
                        "passo": 0, "motivo": "", "pd": np.nan, "p_atraso": np.nan, "ev": 0.0,
                        "valor_teto": np.nan})
    aberto = np.ones(n, bool)

    def negar(mask, passo, motivo):
        nonlocal aberto
        m = aberto & mask.values if hasattr(mask, "values") else aberto & mask
        out.loc[m, ["passo", "motivo"]] = [passo, motivo]
        aberto = aberto & ~m

    # 1. bureau indisponível depois de todas as tentativas -> nega (conservador) e registra
    sem_bureau = b["score"].isna()
    negar(sem_bureau, 1, "bureau indisponível após todas as tentativas")

    # 2. fora da faixa com evidência
    negar(b["restricoes_ativas"] > p.restricoes_max, 2, f"{p.restricoes_max + 1}+ restrições ativas (nunca aprovado no histórico)")
    negar(b["score"] < p.score_min, 2, f"score abaixo de {p.score_min:.0f} (sem histórico de pagamento)")
    negar(b["renda_declarada"] < p.renda_min, 2, f"renda abaixo de R$ {p.renda_min:,.0f} (sem histórico de pagamento)")

    # 3. sinais de alerta
    negar(b["mov_meses_cheque"] > p.meses_cheque_max, 3, "usou cheque especial em 2+ meses no último ano")
    negar(b["mov_saidas_sobre_entradas"] > p.saidas_sobre_entradas_max, 3, "gasta mais de 80% do que entra na conta")
    negar(b["consultas_90_dias"] > p.consultas_90d_max, 3, "8+ consultas ao CPF em 90 dias")
    negar(b["renda_decl_sobre_real"] > p.renda_decl_sobre_real_max, 3, "renda declarada mais que o dobro das entradas reais")

    # 4. teto de valor pela capacidade de pagamento
    sobra = (b["mov_entradas_med"] - b["mov_saidas_med"]).clip(lower=0)
    teto = np.minimum.reduce([
        b["valor_solicitado"].values,
        np.full(n, VALOR_MAX),
        valor_max_por_parcela(p.teto_parcela_sobre_sobra * sobra, b["prazo_meses"]),
        valor_max_por_parcela(p.teto_comprometimento * b["renda_declarada"], b["prazo_meses"]),
    ])
    teto = np.floor(teto * 100) / 100
    out["valor_teto"] = teto
    negar(teto < VALOR_MIN, 4, "parcela mínima (R$ 500) não cabe na sobra mensal")

    # 5. risco x retorno: busca o valor (<= teto) que maximiza o resultado esperado
    idx = np.where(aberto)[0]
    if len(idx):
        L = np.where(b.loc[idx, "restricoes_ativas"] >= 1, taxa_atraso["com_restricao"], taxa_atraso["sem_restricao"])
        fracs = np.linspace(1.0, 0.0, p.pontos_grade, endpoint=False)
        cand = np.outer(teto[idx], fracs)                         # (m, g)
        cand[:, 1:] = np.floor(cand[:, 1:] / 100) * 100           # valores reduzidos em centenas
        cand = np.where(cand < VALOR_MIN, np.nan, cand)
        rep = b.loc[np.repeat(idx, len(fracs))].reset_index(drop=True)
        vals = cand.ravel()
        ok = ~np.isnan(vals)
        pdv = np.full(vals.shape, np.nan)
        pdv[ok] = modelo.pd_contrato(rep[ok], vals[ok])
        pdm = pdv.reshape(cand.shape)
        evm = cand * margem_por_real(pdm, L[:, None])
        evm = np.where(np.isnan(evm), -np.inf, evm)
        j = evm.argmax(axis=1)
        r = np.arange(len(idx))
        best_v, best_pd, best_ev = cand[r, j], pdm[r, j], evm[r, j]
        out.loc[idx, "pd"] = best_pd
        out.loc[idx, "p_atraso"] = L
        out.loc[idx, "ev"] = np.where(np.isfinite(best_ev), best_ev, 0.0)
        aprova = np.isfinite(best_ev) & (best_ev > p.margem_min * np.nan_to_num(best_v))
        # PD do valor teto, para explicar quando o valor foi reduzido por risco
        out.loc[idx, "pd_no_teto"] = pdm[:, 0]
        neg_idx = idx[~aprova]
        out.loc[neg_idx, ["passo", "motivo"]] = [5, "risco de calote alto mesmo com valor reduzido"]
        ap_idx = idx[aprova]
        out.loc[ap_idx, "decisao"] = "APROVADO"
        out.loc[ap_idx, "valor_aprovado"] = np.round(best_v[aprova], 2)
        out.loc[ap_idx, "passo"] = 6
        sol = b.loc[ap_idx, "valor_solicitado"].values
        reduziu = best_v[aprova] < sol - 0.005
        out.loc[ap_idx, "motivo"] = np.where(reduziu, "aprovado com valor reduzido", "aprovado no valor pedido")
    out["valor_aprovado"] = out["valor_aprovado"].round(2)
    return out


def resultado_esperado(decisoes: pd.DataFrame, base: pd.DataFrame, modelo, taxa_atraso: dict) -> pd.Series:
    """EV de cada decisão segundo o modelo (para comparar políticas nos mesmos pedidos)."""
    b = base.reset_index(drop=True)
    v = decisoes["valor_aprovado"].values.astype(float)
    ev = np.zeros(len(b))
    m = v > 0
    if m.any():
        pdv = modelo.pd_contrato(b[m], v[m])
        L = np.where(b.loc[m, "restricoes_ativas"].values >= 1, taxa_atraso["com_restricao"], taxa_atraso["sem_restricao"])
        ev[m] = v[m] * margem_por_real(pdv, L)
    return pd.Series(ev, index=decisoes.index)


def parametros_dict(p: Parametros) -> dict:
    return asdict(p)
