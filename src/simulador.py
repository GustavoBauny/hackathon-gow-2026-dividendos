"""Dados do simulador do painel: o analista liga, desliga e ajusta as regras e vê o efeito na hora.

O painel é uma página estática, sem servidor. Por isso o pipeline deixa pronto em output/simulador.json:
  * para cada pedido novo, as medidas que as regras dos passos 2 a 4 usam;
  * o resultado do passo 5 com os parâmetros padrão, calculado aqui pelo modelo, para todos os pedidos
    (inclusive os que hoje param nos passos 2 e 3). Com os tetos padrão, o simulador usa esse resultado
    exato e reproduz o arquivo de decisões pedido a pedido;
  * a chance de calote de cada pedido para cada valor de R$ 100 em R$ 100 até o pedido, usada quando o
    analista muda um teto do passo 4 ou a margem do passo 5;
  * a evidência do histórico para cada posição de cada regra: quantos contratos e quanto calote
    (Kaplan-Meier) na faixa que a mudança libera ou passa a negar.

A lógica de decisão do simulador fica em src/simulador.js, que reproduz politica_nova passo a passo.
"""
from __future__ import annotations

import base64
from dataclasses import asdict, replace

import numpy as np
import pandas as pd

from features import parcela_price, VALOR_MIN, VALOR_MAX
from modelo import km_relativo
from politica import Parametros, politica_nova, taxa_atraso_de

N_MIN_EVIDENCIA = 30  # abaixo disso, a faixa não tem contratos suficientes para medir o calote


def _entradas(b: pd.DataFrame) -> pd.Series:
    return b["mov_entradas_med"].where(b["mov_entradas_med"] > 0)


def medidas(b: pd.DataFrame) -> pd.DataFrame:
    """As medidas que as regras comparam com os cortes. NaN = a regra não se aplica (como no pipeline)."""
    ent = _entradas(b)
    return pd.DataFrame({
        "restricoes_max": b["restricoes_ativas"],
        "score_min": b["score"],
        "renda_min": b["renda_declarada"],
        "meses_cheque_max": b["mov_meses_cheque"],
        "saidas_sobre_entradas_max": b["mov_saidas_sobre_entradas"],
        "consultas_90d_max": b["consultas_90_dias"],
        "renda_decl_sobre_real_max": b["renda_decl_sobre_real"],
        "tendencia_entradas_max": b["mov_tendencia_entradas"],
        "pedido_sobre_entradas_max": b["valor_solicitado"] / ent,
        "outras_sobre_entradas_max": b["parcelas_outras_instituicoes"] / ent,
    }, index=b.index)


def _pct(v):
    return f"{v * 100:.0f}%"


def _x(v):
    return f"{v:g}".replace(".", ",") + "x"


# Regras que o analista pode mexer. "nega": "maior" nega quando a medida passa do corte; "menor", quando fica abaixo.
REGRAS = [
    # passo 2
    dict(id="restricoes_max", passo=2, nome="Restrições ativas no bureau", nega="maior",
         valores=[0, 1, 2, 3], rotulo=lambda v: f"nega com {v + 1:.0f} ou mais restrições"),
    dict(id="score_min", passo=2, nome="Score mínimo", nega="menor",
         valores=[300, 400, 450, 500, 550, 600], rotulo=lambda v: f"nega score abaixo de {v:.0f}"),
    dict(id="renda_min", passo=2, nome="Renda declarada mínima", nega="menor",
         valores=[1000, 1250, 1500, 1750, 2000], rotulo=lambda v: f"nega renda abaixo de R$ {v:,.0f}".replace(",", ".")),
    # passo 3. ligar_em: corte que o controle assume quando o analista liga uma regra desligada na proposta
    dict(id="meses_cheque_max", passo=3, nome="Cheque especial recorrente", nega="maior", ligar_em=1,
         nota_desligada="Depois das respostas da Fortuna, deixou de negar sozinho: quase sempre vem com gasto acima de 80% "
                        "das entradas, que já é negado. Continua no modelo do passo 5.",
         valores=[0, 1, 2, 3, 5], rotulo=lambda v: f"nega com {v + 1:.0f} ou mais meses no cheque especial"),
    dict(id="saidas_sobre_entradas_max", passo=3, nome="Gasto alto sobre as entradas", nega="maior",
         valores=[0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 1.0], rotulo=lambda v: f"nega saídas acima de {_pct(v)} das entradas"),
    dict(id="consultas_90d_max", passo=3, nome="Consultas ao CPF em 90 dias", nega="maior", ligar_em=7,
         nota_desligada="Depois das respostas da Fortuna, deixou de negar sozinho: todo cliente com 8 ou mais consultas também "
                        "gasta mais de 80% das entradas, que já é negado. Continua no modelo do passo 5.",
         valores=[3, 5, 6, 7, 9, 11], rotulo=lambda v: f"nega com {v + 1:.0f} ou mais consultas"),
    dict(id="renda_decl_sobre_real_max", passo=3, nome="Renda declarada inflada", nega="maior",
         valores=[1.25, 1.5, 1.75, 2.0, 2.5, 3.0], rotulo=lambda v: f"nega renda declarada acima de {_x(v)} as entradas"),
    dict(id="tendencia_entradas_max", passo=3, nome="Pico de entradas antes do pedido", nega="maior",
         valores=[1.2, 1.25, 1.3, 1.35, 1.5, 1.75, 2.0],
         rotulo=lambda v: f"nega entradas recentes {_pct(v - 1)} ou mais acima das anteriores"),
    dict(id="pedido_sobre_entradas_max", passo=3, nome="Pedido excessivo", nega="maior",
         valores=[3, 4, 5, 6, 8, 10], rotulo=lambda v: f"nega pedido acima de {_x(v)} as entradas do mês"),
    dict(id="outras_sobre_entradas_max", passo=3, nome="Dívida em outros bancos", nega="maior",
         valores=[0.2, 0.25, 0.3, 0.35, 0.4, 0.5], rotulo=lambda v: f"nega dívidas acima de {_pct(v)} das entradas"),
]

TETOS = [
    dict(id="teto_parcela_sobre_sobra", nome="Parcela sobre a sobra mensal", valores=[0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6],
         rotulo=lambda v: f"parcela até {_pct(v)} da sobra (entradas − saídas)"),
    dict(id="teto_parcela_sobre_entradas", nome="Parcela sobre as entradas reais", valores=[0.2, 0.25, 0.3, 0.35, 0.4, 0.5],
         rotulo=lambda v: f"parcela até {_pct(v)} das entradas reais"),
    dict(id="teto_comprometimento", nome="Parcela sobre a renda declarada", valores=[0.2, 0.25, 0.3, 0.35, 0.4, 0.5],
         rotulo=lambda v: f"parcela até {_pct(v)} da renda declarada"),
]

MARGENS = [0.0, 0.005, 0.01, 0.02, 0.03, 0.05]


def _medidas_teto(h: pd.DataFrame) -> pd.DataFrame:
    """Para o histórico: a parcela do valor aprovado sobre cada base de capacidade."""
    parc = parcela_price(h["valor_aprovado"], h["prazo_meses"])
    sobra = (h["mov_entradas_med"] - h["mov_saidas_med"]).clip(lower=1)
    ent = np.minimum(h["mov_entradas_med"], h["mov_entradas_ult3"]).where(lambda s: s > 0)
    return pd.DataFrame({"teto_parcela_sobre_sobra": parc / sobra,
                         "teto_parcela_sobre_entradas": parc / ent,
                         "teto_comprometimento": parc / h["renda_declarada"]}, index=h.index)


def _km(h: pd.DataFrame, mask: pd.Series) -> dict:
    sub = h[mask.fillna(False).values]
    pd_, n = km_relativo(sub)
    return {"n": int(n), "pd": None if n == 0 or not np.isfinite(pd_) else round(float(pd_), 4)}


def _faixa(x: pd.Series, padrao: float, v: float, nega: str) -> pd.Series:
    """Contratos entre o corte padrão e o corte v: os que a mudança libera (ou passa a negar)."""
    lo, hi = min(padrao, v), max(padrao, v)
    if nega == "maior":   # nega x > corte: a faixa entre os cortes é (lo, hi]
        return (x > lo) & (x <= hi)
    return (x >= lo) & (x < hi)  # nega x < corte: a faixa é [lo, hi)


def _dispara(x: pd.Series, corte: float | None, nega: str) -> pd.Series:
    """Mesma comparação do pipeline: medida ausente (NaN) não dispara a regra; corte None = regra desligada."""
    if corte is None:
        return pd.Series(False, index=x.index)
    return ((x > corte) if nega == "maior" else (x < corte)).fillna(False)


def evidencia(hist: pd.DataFrame) -> dict:
    """Calote no histórico para cada regra e posição do controle.

    Mede só os contratos que a mudança de fato afeta: os que nenhuma OUTRA regra dos passos 2 e 3 negaria.
    Para um teto do passo 4, os contratos sem nenhum sinal de alerta e dentro dos outros dois tetos.
      grupo_padrao: os que só esta regra nega com o corte padrão (o que desligar a regra libera);
      faixas[k]:    os que ficam entre o corte padrão e o corte k (o que a mudança libera ou passa a negar).
    Regra desligada na proposta (corte padrão None): grupo_padrao fica vazio, e faixas[k] traz os que ligar a
    regra no corte k passaria a negar.
    """
    pad = asdict(Parametros())
    med, med_teto = medidas(hist), _medidas_teto(hist)
    dispara = {r["id"]: _dispara(med[r["id"]], pad[r["id"]], r["nega"]) for r in REGRAS}
    cabe = {t["id"]: (med_teto[t["id"]] <= pad[t["id"]]).fillna(False) for t in TETOS}
    out = {}
    for r in REGRAS:
        outras = np.logical_or.reduce([d.values for k, d in dispara.items() if k != r["id"]])
        base = pd.Series(~outras, index=hist.index)
        x, p0 = med[r["id"]], pad[r["id"]]
        if p0 is None:
            out[r["id"]] = {"grupo_padrao": {"n": 0, "pd": None},
                            "faixas": [_km(hist, base & _dispara(x, v, r["nega"])) for v in r["valores"]]}
            continue
        out[r["id"]] = {
            "grupo_padrao": _km(hist, base & dispara[r["id"]]),
            "faixas": [None if v == p0 else _km(hist, base & _faixa(x, p0, v, r["nega"])) for v in r["valores"]],
        }
    nenhum_alerta = ~np.logical_or.reduce([d.values for d in dispara.values()])
    for t in TETOS:
        outros = np.logical_and.reduce([c.values for k, c in cabe.items() if k != t["id"]])
        base = pd.Series(nenhum_alerta & outros, index=hist.index)
        x, p0 = med_teto[t["id"]], pad[t["id"]]
        out[t["id"]] = {
            "grupo_padrao": _km(hist, base & (x > p0).fillna(False)),
            "faixas": [None if v == p0 else _km(hist, base & _faixa(x, p0, v, "maior")) for v in t["valores"]],
        }
    return out


def _resultado_passo5(novos: pd.DataFrame, modelo, taxa_atraso: dict) -> pd.DataFrame:
    """Passo 5 com os tetos e a margem padrão para TODOS os pedidos: desliga os passos 2 e 3."""
    sem_regras = replace(Parametros(), **{r["id"]: None for r in REGRAS})
    return politica_nova(novos, modelo, taxa_atraso, sem_regras)


def _grade_pd(novos: pd.DataFrame, modelo) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """PD para R$ 500, 600, ..., até o valor pedido (limitado a R$ 30 mil), mais o próprio valor pedido."""
    vmax = np.minimum(novos["valor_solicitado"].values, VALOR_MAX)
    tem = novos["score"].notna().values & (vmax >= VALOR_MIN)
    grades = []
    for i in range(len(novos)):
        if not tem[i]:
            grades.append(np.array([]))
            continue
        g = np.arange(VALOR_MIN, np.floor(vmax[i] / 100) * 100 + 1, 100.0)
        if vmax[i] - g[-1] > 0.005:
            g = np.append(g, vmax[i])
        grades.append(g)
    cont = np.array([len(g) for g in grades])
    ini = np.concatenate([[0], np.cumsum(cont)[:-1]])
    vals = np.concatenate([g for g in grades if len(g)])
    rep = novos.loc[np.repeat(np.arange(len(novos)), cont)].reset_index(drop=True)
    pdv = modelo.pd_contrato(rep, vals)
    return ini, cont, pdv


def montar(novos: pd.DataFrame, hist: pd.DataFrame, modelo, taxa_atraso: dict, oficial: pd.DataFrame,
           atual: pd.DataFrame) -> dict:
    """oficial: decisões da política proposta (padrão); atual: decisões da política atual com ev_modelo."""
    b = novos.reset_index(drop=True)
    p = Parametros()
    p5 = _resultado_passo5(b, modelo, taxa_atraso)
    ini, cont, pdv = _grade_pd(b, modelo)
    pd_u16 = np.round(np.clip(pdv, 0, 1) * 65535).astype("<u2")
    med = medidas(b)
    sobra = (b["mov_entradas_med"] - b["mov_saidas_med"]).clip(lower=0)

    def col(s, casas=6):
        return [None if (v is None or not np.isfinite(v)) else round(float(v), casas) for v in np.asarray(s, float)]

    passo5_aprova = p5["decisao"].eq("APROVADO").values
    pedidos = {
        "id": b["id_pedido"].tolist(),
        "tem_bureau": b["score"].notna().tolist(),
        "valor_solicitado": col(b["valor_solicitado"], 2),
        "prazo": b["prazo_meses"].astype(int).tolist(),
        "sobra": col(sobra, 4),
        "renda": col(b["renda_declarada"], 2),
        "entradas_min": col(np.minimum(b["mov_entradas_med"], b["mov_entradas_ult3"]), 4),
        "atraso": col(taxa_atraso_de(b, taxa_atraso), 4),
        "medidas": {k: col(med[k], 6) for k in med.columns},
        # se cada regra dispara com o corte padrão (exato, do pipeline; o simulador usa quando o corte não mudou)
        "dispara_padrao": {r["id"]: _dispara(med[r["id"]], getattr(p, r["id"]), r["nega"]).astype(int).tolist()
                           for r in REGRAS},
        # passo 4 e 5 com os parâmetros padrão (exatos, do pipeline)
        "teto_padrao": col(p5["valor_teto"], 2),
        "p5_aprova": passo5_aprova.tolist(),
        "p5_valor": col(np.where(passo5_aprova, p5["valor_aprovado"], 0.0), 2),
        "p5_pd": col(p5["pd"], 6),
        "p5_ev": col(np.where(passo5_aprova, p5["ev"], 0.0), 4),
        "p5_passo": p5["passo"].astype(int).tolist(),
        # grade de PD por valor
        "grade_ini": ini.astype(int).tolist(),
        "grade_n": cont.astype(int).tolist(),
        # referência
        "oficial_decisao": oficial["decisao"].tolist(),
        "oficial_passo": oficial["passo"].astype(int).tolist(),
        "oficial_valor": col(oficial["valor_aprovado"], 2),
        "atual_decisao": atual["decisao"].tolist(),
        "atual_valor": col(atual["valor_aprovado"], 2),
        "atual_ev": col(atual["ev_modelo"], 4),
    }
    regras = [{"id": r["id"], "passo": r["passo"], "nome": r["nome"], "nega": r["nega"], "valores": r["valores"],
               "ligar_em": r.get("ligar_em"), "nota_desligada": r.get("nota_desligada"), "rotulos": [r["rotulo"](v) for v in r["valores"]]} for r in REGRAS]
    tetos = [{"id": r["id"], "nome": r["nome"], "valores": r["valores"], "rotulos": [r["rotulo"](v) for v in r["valores"]]}
             for r in TETOS]
    return {
        "parametros_padrao": asdict(p),
        "regras": regras,
        "tetos": tetos,
        "margens": MARGENS,
        "valor_min": VALOR_MIN, "valor_max": VALOR_MAX,
        "ganhos": {"em_dia": 0.15, "atraso": 0.05, "calote": 0.60},
        "n_min_evidencia": N_MIN_EVIDENCIA,
        "evidencia": evidencia(hist),
        "pedidos": pedidos,
        "grade_pd_u16_b64": base64.b64encode(pd_u16.tobytes()).decode("ascii"),
    }
