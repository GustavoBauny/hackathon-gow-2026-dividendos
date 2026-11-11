"""Padrões encontrados no histórico, recalculados a partir dos dados para o painel.

Os padrões foram descobertos por agentes de IA (Claude) que analisaram o histórico por ângulos
diferentes; cada achado foi refeito do zero por um agente verificador que tentou refutá-lo
(ver descoberta/). Aqui cada padrão é só uma definição em código: todos os números exibidos no
painel (taxa do grupo, comparação, quantos clientes afeta) são calculados nesta execução.

Inadimplência = calotes observados / exposição observada (target.py): conta os contratos em
andamento pela fração da janela de risco que já passou, sem tratar "em dia há 1 mês" como bom pagador.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from features import LIMIARES, parcela_price
from politica import politica_atual
from risco import regras_duras

L = LIMIARES
COMO_IA = ("7 agentes de IA analisaram o histórico, cada um por um ângulo (bureau, movimentação da conta, "
           "cadastro e renda, valor e capacidade, atraso, mineração de regras, auditoria da política atual)")


def _taxa(df: pd.DataFrame) -> float:
    e = df["exposicao"].sum()
    return float(min(1.0, df["calote_obs"].sum() / e)) if e > 0 else float("nan")


def _atraso(df: pd.DataFrame) -> float:
    s = df[~df["calote_obs"] & (df["frac_vencida"] >= 0.5)]
    return float(s["atraso_obs"].mean()) if len(s) else float("nan")


def _p(x: float) -> str:
    return "—" if x is None or np.isnan(x) else f"{x * 100:.0f}%"


def _flags(b: pd.DataFrame, valor) -> dict[str, np.ndarray]:
    d = regras_duras(b, valor)
    f = {
        "P01": d["capacidade"], "P02": d["saidas"], "P03": d["renda_inflada"],
        "P04": (b["pedido_sobre_entradas"] > L["pedido_sobre_entradas"]).fillna(False).to_numpy(bool),
        "P05": (b["outras_sobre_entradas"] > L["outras_sobre_entradas"]).fillna(False).to_numpy(bool),
        "P07": (b["mov_entradas_cv"] > L["cv_entradas"]).fillna(False).to_numpy(bool),
    }
    f["duras"] = f["P01"] | f["P02"] | f["P03"]
    f["algum_risco"] = f["duras"] | f["P04"] | f["P05"] | f["P07"]
    return f


# Cada padrão: grupo, característica (completa a frase "Clientes ..."), máscara, universo de comparação,
# leitura de negócio, uso na política. Universo: "todos" os aprovados, "sem_duras" (fora das 3 regras de
# calote certo) ou "limpos" (sem nenhum fator de risco: para mostrar oportunidades que a política atual nega).
PADROES = [
    dict(id="P01", grupo="Capacidade de pagamento (depende do valor aprovado)", universo="todos",
         caracteristica=f"cuja parcela passa de {L['parcela_sobre_sobra']:.0%} da sobra mensal da conta (entradas menos saídas)",
         mascara=lambda b, f: f["P01"],
         leitura="O degrau é exato em 50%: até 45% a inadimplência é a da média; acima de 50%, todos dão calote. "
                 "O que conta é o valor APROVADO: quem pediu demais mas foi aprovado num valor menor pagou normalmente.",
         acao="Passo 4: o valor aprovado é limitado para a parcela caber em 45% da sobra (folga de 5 p.p.).",
         regra_tecnica="parcela_price(valor_aprovado, prazo) / (média entradas − média saídas) > 0,50, ou sobra ≤ 0"),
    dict(id="P02", grupo="Sinais de alerta na conta", universo="todos",
         caracteristica=f"cujas saídas chegam a {L['saidas_sobre_entradas']:.0%} ou mais das entradas da conta",
         mascara=lambda b, f: f["P02"],
         leitura="Perfil de quem gasta tudo o que entra. Costuma vir junto com um mês de gasto muito acima do normal, "
                 "uso do cheque especial e muitas consultas ao CPF: esses sinais são marcadores do mesmo perfil.",
         acao="Passo 3: nega.", regra_tecnica="média saídas / média entradas ≥ 0,90"),
    dict(id="P03", grupo="Sinais de alerta na conta", universo="todos",
         caracteristica=f"que declaram renda maior que {L['renda_inflada']:.0f} vezes o que de fato entra na conta",
         mascara=lambda b, f: f["P03"],
         leitura="Renda declarada inflada. Aparece em contas novas (1 ou 2 meses de movimentação). "
                 "Não é falta de capacidade: a parcela costuma caber na sobra.",
         acao="Passo 3: nega.", regra_tecnica="renda_declarada / média entradas > 2"),
    dict(id="P04", grupo="Sinais de alerta na conta", universo="sem_duras",
         caracteristica=f"que pedem mais de {L['pedido_sobre_entradas']:.0f} vezes o que entra por mês na conta",
         mascara=lambda b, f: f["P04"],
         leitura="Pedido desproporcional à realidade da conta. Reduzir o valor não resolve: entre os que tiveram o valor "
                 "cortado pela política atual, o risco continuou alto. Explica por que 'valor reduzido ao teto de 30%' "
                 "parecia um sinal de risco.",
         acao="Passo 3: nega (não oferece valor menor).", regra_tecnica="valor_solicitado / média entradas > 6"),
    dict(id="P05", grupo="Sinais de alerta na conta", universo="sem_duras",
         caracteristica=f"cujas parcelas em outras instituições passam de {L['outras_sobre_entradas']:.0%} do que entra na conta",
         mascara=lambda b, f: f["P05"],
         leitura="Endividamento alto medido contra a entrada real. A mesma conta contra a renda declarada não "
                 "separa bons de maus: o que importa é o que de fato entra. Também dobra a chance de atraso.",
         acao="Passo 3: nega (resultado esperado negativo).",
         regra_tecnica="parcelas_outras_instituicoes / média entradas > 0,35"),
    dict(id="P07", grupo="Sinais de alerta na conta", universo="sem_duras",
         caracteristica=f"com entradas mensais instáveis (variação acima de {L['cv_entradas']:.0%} de um mês para outro)",
         mascara=lambda b, f: f["P07"],
         leitura="Só aparece em autônomos e empresários. Com entradas estáveis, autônomos, empresários e assalariados "
                 "têm o mesmo risco: o tipo de vínculo, sozinho, não importa.",
         acao="Passo 3: nega. O grupo fica perto do ponto de equilíbrio; o analista pode desligar a regra.",
         regra_tecnica="desvio padrão / média das entradas mensais > 0,35"),
    dict(id="P06", grupo="Oportunidades que a política atual perde", universo="limpos",
         caracteristica="com score do bureau até 600 e sem outros fatores de risco",
         mascara=lambda b, f: (b["score"] <= 600).to_numpy(),
         leitura="O score não prevê inadimplência. Score baixo aqui significa histórico curto no bureau (menos de "
                 "12 meses), não mau pagador: é o 'bom pagador com pouca movimentação de crédito' que a Fortuna "
                 "suspeitava estar negando.",
         acao="Removido o corte de score 600 (mantido só o piso de 450, até onde o piloto testou).",
         regra_tecnica="score ≤ 600 (gerado a partir de meses_historico_bureau < 12)"),
    dict(id="P08", grupo="Oportunidades que a política atual perde", universo="sem_duras", metrica="atraso",
         caracteristica="com 1 restrição ativa no bureau",
         mascara=lambda b, f: (b["restricoes_ativas"] == 1).to_numpy(),
         leitura="Uma restrição não aumenta o calote; aumenta o atraso (rende +5% em vez de +15%), o que ainda dá lucro. "
                 "Com 2 ou mais restrições não há nenhum contrato no histórico para avaliar.",
         acao="Aceita até 1 restrição; nega 2 ou mais (sem evidência).", regra_tecnica="restricoes_ativas == 1"),
    dict(id="P09", grupo="Oportunidades que a política atual perde", universo="limpos",
         caracteristica="com renda declarada entre R$ 1.500 e R$ 2.000 e sem outros fatores de risco",
         mascara=lambda b, f: ((b["renda_declarada"] > 1500) & (b["renda_declarada"] <= 2000)).to_numpy(),
         leitura="O nível da renda não muda o risco depois que o valor é ajustado à sobra da conta.",
         acao="Removido o corte de renda 2.000 (mantido o piso de 1.500, até onde o piloto testou).",
         regra_tecnica="1.500 < renda_declarada ≤ 2.000"),
    dict(id="P10", grupo="Outros fatores de risco (entram no modelo)", universo="limpos",
         caracteristica="aposentados, sem outros fatores de risco",
         mascara=lambda b, f: (b["tipo_vinculo"] == "aposentado").to_numpy(),
         leitura="Risco menor que a média. A idade, sozinha, não explica o efeito.",
         acao="Entra no modelo de risco (passo 5) como fator que reduz o risco.", regra_tecnica="tipo_vinculo == aposentado"),
    dict(id="P11", grupo="Outros fatores de risco (entram no modelo)", universo="limpos",
         caracteristica=f"com menos de {L['bureau_curto_meses']} meses de histórico no bureau, sem outros fatores de risco",
         mascara=lambda b, f: (b["meses_historico_bureau"] < L["bureau_curto_meses"]).to_numpy(),
         leitura="Efeito pequeno: o risco sobe, mas continua bem abaixo do ponto em que o empréstimo dá prejuízo.",
         acao="Entra no modelo de risco (passo 5); sozinho não nega.", regra_tecnica="meses_historico_bureau < 36"),
    dict(id="P12", grupo="Atributo sensível (não usado na decisão)", universo="sem_duras", sensivel=True,
         caracteristica="com CEP começando em 1 e pedido a partir de abril de 2025",
         mascara=lambda b, f: ((b["cep"].astype(str).str[0] == "1") & (b["data_pedido"] >= "2025-04-01")).to_numpy(),
         leitura="Há um efeito regional, mas decidir crédito por CEP é discriminatório. Esses clientes ficam perto do "
                 "ponto de equilíbrio, então deixar de usar o CEP custa quase nada.",
         acao="Não usado. Gênero, idade e estado civil foram testados e não têm efeito.",
         regra_tecnica="cep[0] == '1' e data_pedido ≥ 2025-04-01"),
]


def calcular_padroes(hist: pd.DataFrame, novos: pd.DataFrame, parcelas: pd.DataFrame | None = None) -> dict:
    a = hist[(hist["decisao"] == "aprovado") & (hist["exposicao"] > 0)].copy()
    for c in ["calote_obs", "atraso_obs", "maduro"]:
        a[c] = a[c].astype(bool)
    fa = _flags(a, a["valor_aprovado"].to_numpy(float))               # aprovados: no valor aprovado
    fh = _flags(hist, hist["valor_solicitado"].to_numpy(float))       # histórico: no valor pedido
    fn = _flags(novos, novos["valor_solicitado"].to_numpy(float))     # novos: no valor pedido
    universos = {"todos": np.ones(len(a), bool), "sem_duras": ~fa["duras"], "limpos": ~fa["algum_risco"]}
    rotulo_ref = {"todos": "da média dos aprovados", "sem_duras": "dos demais aprovados",
                  "limpos": "dos demais clientes sem fatores de risco"}
    taxa_media = _taxa(a)

    saida = []
    for spec in PADROES:
        u = universos[spec["universo"]]
        m = np.asarray(spec["mascara"](a, fa), bool)
        seg, ref = a[u & m], a[u & ~m]
        mh = np.asarray(spec["mascara"](hist, fh), bool)
        mn = np.asarray(spec["mascara"](novos, fn), bool)
        if spec["universo"] == "limpos":   # oportunidades: conta só quem não tem outro fator de risco
            mh, mn = mh & ~fh["algum_risco"], mn & ~fn["algum_risco"]
        t, tr = _taxa(seg), _taxa(ref)
        at, atr = _atraso(seg), _atraso(ref)
        mat = seg[seg["maduro"]]
        frase = (f"Clientes {spec['caracteristica']} têm inadimplência de {_p(t)}, contra {_p(tr)} {rotulo_ref[spec['universo']]}")
        if spec.get("metrica") == "atraso":
            frase += f", mas atrasam parcelas em {_p(at)} dos casos, contra {_p(atr)}"
        frase += f". Afeta {int(mn.sum())} dos 2.000 pedidos novos."
        saida.append({
            "id": spec["id"], "grupo": spec["grupo"], "titulo": frase, "leitura": spec["leitura"],
            "taxa_segmento": t, "taxa_referencia": tr, "atraso_segmento": at, "atraso_referencia": atr,
            "n_hist": int(mh.sum()), "n_aprovados": int(len(seg)), "n_novos": int(mn.sum()),
            "regra_tecnica": spec["regra_tecnica"], "acao": spec["acao"], "sensivel": bool(spec.get("sensivel", False)),
            "como": COMO_IA + "; o achado foi confirmado de forma independente por um agente verificador.",
            "verificacao": (f"Contratos maduros (janela de risco inteira observada): {int(mat['calote_obs'].sum())} calotes "
                            f"em {len(mat)}. Comparação dentro de: {rotulo_ref[spec['universo']].replace('dos ', '').replace('da ', '')}."),
        })

    return {"taxa_media": taxa_media, "padroes": saida, "fatos": _fatos(hist, a, fa, fh, parcelas)}


def _fatos(hist, a, fa, fh, parcelas) -> list[dict]:
    """Descobertas sobre o funcionamento da base que sustentam a política (todas recalculadas)."""
    fatos = []
    # política atual e piloto reproduzidas
    h = hist.reset_index(drop=True)
    at = h["politica_aplicada"] == "atual"
    rep = politica_atual(h[at])
    ok_dec = rep["decisao"].str.lower().to_numpy() == h.loc[at, "decisao"].to_numpy()
    dif_valor = (rep["valor_aprovado"] - h.loc[at, "valor_aprovado"].fillna(0)).abs().max()
    fatos.append({"titulo": "A regra da política atual foi reproduzida",
                  "texto": f"Aplicando score > 600, renda > R$ 2.000, sem restrição e parcela até 30% da renda, "
                           f"{ok_dec.mean():.1%} das {int(at.sum())} decisões históricas da política atual batem "
                           f"(valor aprovado com diferença máxima de R$ {dif_valor:.2f})."})
    pi = h[h["politica_aplicada"] == "piloto"]
    crit = (pi["score"] > 450) & (pi["renda_declarada"] > 1500) & (pi["restricoes_ativas"] <= 1)
    acerto = (crit == (pi["decisao"] == "aprovado")).mean()
    fatos.append({"titulo": "A IA descobriu a regra do piloto",
                  "texto": f"O piloto aprovou quem tinha score > 450, renda > R$ 1.500 e no máximo 1 restrição "
                           f"(confere em {acerto:.1%} dos {len(pi)} pedidos do piloto). É a faixa em que há evidência "
                           f"de pagamento; fora dela a nova política não aposta."})
    curto = hist["meses_historico_bureau"] < 12
    fatos.append({"titulo": "O score baixo vem do histórico curto no bureau",
                  "texto": f"Com menos de 12 meses de histórico, o score fica entre {hist.loc[curto, 'score'].min():.0f} e "
                           f"{hist.loc[curto, 'score'].max():.0f}; com 12 meses ou mais, a média é "
                           f"{hist.loc[~curto, 'score'].mean():.0f}. Por isso o corte em 600 nega quem é novo no crédito, "
                           f"não quem paga mal."})
    s = hist[fh["P02"]]
    ch = (a["mov_meses_cheque"] >= 2).to_numpy() & ~fa["duras"]
    mat = a[ch & a["maduro"].to_numpy()]
    fatos.append({"titulo": "Consultas ao CPF e cheque especial são sintomas, não causa",
                  "texto": f"Dos {int((hist['consultas_90_dias'] >= 8).sum())} pedidos com 8+ consultas em 90 dias, "
                           f"{int((s['consultas_90_dias'] >= 8).sum())} estão no perfil 'gasta tudo o que entra' (P02). "
                           f"Fora das regras de calote certo, cheque especial em 2+ meses tem {int(ch.sum())} contratos e "
                           f"{int(mat['calote_obs'].sum())} calotes em {len(mat)} maduros: depois de considerar os outros "
                           f"fatores, não muda o risco. Por isso não viraram regras próprias."})
    if parcelas is not None:
        pg = parcelas[parcelas["data_pagamento"].notna()]
        fatos.append({"titulo": "Calote é definitivo",
                      "texto": f"Nenhuma parcela paga atrasou mais de {int(pg['dias_atraso'].max())} dias. "
                               f"Parcela vencida e não paga há mais de 60 dias nunca volta a ser paga: é calote. "
                               f"O calote começa até 60% do prazo, o que permite estimar o risco dos contratos em andamento."})
    return fatos
