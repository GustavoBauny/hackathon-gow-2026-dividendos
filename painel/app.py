"""Painel de experimentação da Fortuna Crédito (time Dividendos).

    streamlit run painel/app.py

A IA sugere, o analista decide: os padrões e a política proposta vêm do pipeline
(`python gerar_decisoes.py`). No painel o analista liga/desliga regras, ajusta limiares, vê o impacto
no histórico e nos 2.000 pedidos novos e grava a versão aprovada em `politica_aprovada.json`,
que é a versão que o pipeline usa para gerar o CSV.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from features import LIMIARES, parcela_price  # noqa: E402
from politica import (PASSOS, Parametros, Regra, carregar_parametros,  # noqa: E402
                      parametros_de_dict, parametros_dict, politica_atual, politica_nova, resultado_esperado)
from risco import FATORES_ATRASO, FATORES_CALOTE, ModeloRisco, regras_duras  # noqa: E402

# Caminhos sobrescrevíveis por variável de ambiente (os testes usam cópias temporárias)
DADOS = Path(os.environ.get("FORTUNA_DADOS") or RAIZ / "data")
APROVADA = Path(os.environ.get("FORTUNA_POLITICA_APROVADA") or RAIZ / "politica_aprovada.json")

st.set_page_config(page_title="Fortuna · Política de crédito", page_icon="💳", layout="wide")


def num(v, casas: int = 0) -> str:
    """Número em pt-BR: num(1287.5, 1) -> "1.287,5"."""
    return f"{float(v):,.{casas}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def brl(v: float) -> str:
    return f"R$ {num(abs(v))}" if v >= 0 else f"−R$ {num(abs(v))}"


def inteiro(v) -> str:
    """Inteiro com separador de milhar pt-BR: 1287 -> "1.287"."""
    return num(round(float(v)))


def brl_delta(v: float) -> str:
    """Variação em R$ com sinal ASCII: o st.metric só entende "-" (não "−") como queda."""
    return f"{'-' if round(v) < 0 else '+'}R$ {num(abs(v))}"


class _LimiarBR(float):
    """Limiar que se formata em pt-BR dentro do texto da regra ("{limiar}", "{limiar:.0%}")."""

    def __format__(self, spec: str) -> str:
        if not spec:
            return num(self) if float(self).is_integer() else format(float(self), "g").replace(".", ",")
        return format(float(self), spec).replace(",", "_").replace(".", ",").replace("_", ".")


def texto_regra(r: Regra) -> str:
    return r.motivo.format(limiar=_LimiarBR(r.limiar))


ROTULO_LIMIAR = {
    "restricoes": "Negar a partir de quantas restrições",
    "score_min": "Negar score até",
    "renda_min": "Negar renda declarada até (R$)",
    "gasta_tudo": "Negar quando saídas ÷ entradas ≥",
    "renda_inflada": "Negar quando renda declarada ÷ entradas >",
    "pedido_excessivo": "Negar quando pedido ÷ entradas mensais >",
    "divida_alta": "Negar quando parcelas em outras instituições ÷ entradas >",
    "entradas_instaveis": "Negar quando a variação das entradas >",
}


def pct(v, casas: int = 1) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v * 100:.{casas}f}%".replace(".", ",")


# ------------------------------------------------------------------ dados
ARTEFATOS = ["novos_base.parquet", "hist_base.parquet", "modelo_risco.json", "resumo_execucao.json", "padroes.json"]


def versao_dados() -> tuple:
    """Pasta e data de modificação de cada artefato: muda sempre que o pipeline regrava algum deles."""
    return (str(DADOS),) + tuple((DADOS / f).stat().st_mtime_ns if (DADOS / f).exists() else None for f in ARTEFATOS)


@st.cache_resource
def carregar(versao: tuple):
    pasta = Path(versao[0])
    if any(not (pasta / f).exists() for f in ARTEFATOS):
        return None
    novos = pd.read_parquet(pasta / "novos_base.parquet").reset_index(drop=True)
    hist = pd.read_parquet(pasta / "hist_base.parquet")
    modelo = ModeloRisco.carregar(pasta / "modelo_risco.json")
    resumo = json.loads((pasta / "resumo_execucao.json").read_text(encoding="utf-8"))
    padroes = json.loads((pasta / "padroes.json").read_text(encoding="utf-8"))
    return novos, hist, modelo, resumo, padroes


def recarregar_dados() -> None:
    st.cache_resource.clear()
    st.cache_data.clear()


VERSAO = versao_dados()
pacote = carregar(VERSAO)
if pacote is None:
    st.error("Rode primeiro `python gerar_decisoes.py` para gerar os artefatos em data/.")
    st.stop()
novos, hist, modelo, resumo, padroes = pacote
hist_ap = hist[(hist["decisao"] == "aprovado") & (hist["exposicao"] > 0)].copy()
hist_ap["calote_obs"] = hist_ap["calote_obs"].astype(bool)
# Mesma base da aba 1 para os padrões P04, P05 e P07: aprovados fora das 3 regras de calote certo
_duras = regras_duras(hist_ap, hist_ap["valor_aprovado"].to_numpy(float))
hist_sem_duras = hist_ap[~(_duras["capacidade"] | _duras["saidas"] | _duras["renda_inflada"])]
PADROES_SEM_DURAS = {"P04", "P05", "P07"}


def taxa_ajustada(df: pd.DataFrame) -> float:
    """Inadimplência estimada com contratos em andamento: calotes / exposição observada."""
    e = df["exposicao"].sum()
    return float(min(1.0, df["calote_obs"].sum() / e)) if e > 0 else float("nan")


@st.cache_data(show_spinner="Aplicando a política aos 2.000 pedidos…")
def aplicar(params_json: str, versao: tuple) -> pd.DataFrame:
    dec = politica_nova(novos, modelo, parametros_de_dict(json.loads(params_json)))
    dec["ev_modelo"] = resultado_esperado(dec, novos, modelo).values
    return dec


@st.cache_data
def aplicar_atual(versao: tuple) -> pd.DataFrame:
    atual = politica_atual(novos).reset_index(drop=True)
    atual["ev_modelo"] = resultado_esperado(atual, novos, modelo).values
    return atual


# ------------------------------------------------------------------ barra lateral: política em análise
# Cada controle tem chave fixa e o seu valor vive em st.session_state: o valor inicial vem da versão
# aprovada (ou da proposta da IA) e, depois, vale o que o analista escolheu. Assim nenhum ajuste se perde
# e os rótulos já mostram o ajuste na mesma execução.
if "base" not in st.session_state:
    st.session_state.base = parametros_dict(carregar_parametros(APROVADA))


def iniciar_controles(p: dict, forcar: bool = False) -> None:
    """Coloca os valores de `p` nos controles (forcar=True sobrescreve o que o analista ajustou)."""
    iniciais = {"cap_sobra_on": p["teto_parcela_sobre_sobra"] is not None,
                "cap_sobra": float(p["teto_parcela_sobre_sobra"] or 0.45),
                "cap_renda_on": p["teto_comprometimento"] is not None,
                "cap_renda": float(p["teto_comprometimento"] or 0.30),
                "mod_on": bool(p["usar_modelo"]), "mod_margem": float(p["margem_min"])}
    for r in p["regras"]:
        iniciais[f"a_{r['id']}"] = bool(r["ativa"])
        iniciais[f"l_{r['id']}"] = float(r["limiar"])
    for k, v in iniciais.items():
        if forcar or k not in st.session_state:
            st.session_state[k] = v


def voltar_a_proposta() -> None:
    st.session_state.base = parametros_dict(Parametros())
    iniciar_controles(st.session_state.base, forcar=True)


iniciar_controles(st.session_state.base)
ss = st.session_state
B = ss.base
regras_vivas = [{**r, "ativa": bool(ss[f"a_{r['id']}"]), "limiar": float(ss[f"l_{r['id']}"])} for r in B["regras"]]
P = {"regras": regras_vivas, "teto_parcela_sobre_sobra": float(ss["cap_sobra"]) if ss["cap_sobra_on"] else None,
     "teto_comprometimento": float(ss["cap_renda"]) if ss["cap_renda_on"] else None,
     "usar_modelo": bool(ss["mod_on"]), "margem_min": float(ss["mod_margem"])}
dec = aplicar(json.dumps(P, sort_keys=True), VERSAO)
# Pedidos que o modelo do passo 5 negaria de qualquer forma (explica por que desligar uma regra pode não mudar nada)
nega_modelo = (P["usar_modelo"] & (dec["margem"] < P["margem_min"]) & novos["score"].notna()).to_numpy(bool)

st.sidebar.title("Política em análise")
st.sidebar.caption("A IA sugeriu as regras abaixo. Ligue, desligue ou ajuste o limiar: o painel recalcula "
                   "o efeito no histórico e nos 2.000 pedidos novos.")
st.sidebar.button("Voltar à proposta da IA", on_click=voltar_a_proposta)

for titulo, passo in [("Fora da faixa com evidência", 2), ("Sinais de alerta", 3)]:
    st.sidebar.markdown(f"**{titulo}**")
    for r in [r for r in regras_vivas if r["passo"] == passo]:
        with st.sidebar.expander(f"{'✅' if r['ativa'] else '⏸️'} {texto_regra(Regra(**r))}"):
            st.checkbox("Regra ativa", key=f"a_{r['id']}")
            lim0 = next(b["limiar"] for b in B["regras"] if b["id"] == r["id"])
            passo_inteiro = float(lim0).is_integer() and abs(lim0) >= 2
            st.number_input(ROTULO_LIMIAR.get(r["id"], f"Limiar ({r['coluna']} {r['op']} …)"),
                            step=1.0 if passo_inteiro else 0.05, key=f"l_{r['id']}")
            base_h = hist_sem_duras if r["padrao"] in PADROES_SEM_DURAS else hist_ap
            m = Regra(**r).mascara(base_h)
            if not m.any():
                st.caption("Nunca aprovado no histórico: não há dados de pagamento para este grupo.")
            else:
                st.caption(f"Histórico: {inteiro(m.sum())} contratos aprovados no grupo, inadimplência "
                           f"{pct(taxa_ajustada(base_h[m]))} contra {pct(taxa_ajustada(base_h[~m]))} dos demais. "
                           f"Padrão {r['padrao']}.")
            grupo = Regra(**r).mascara(novos) & novos["score"].notna().to_numpy(bool)
            n_grupo, n_mod = int(grupo.sum()), int((grupo & nega_modelo).sum())
            st.caption(f"Pedidos novos no grupo: {inteiro(n_grupo)}.")
            if n_grupo and n_mod == n_grupo:
                st.caption(f"Desligar esta regra não muda nenhuma decisão: o modelo do passo 5 negaria todos esses "
                           f"{inteiro(n_grupo)} pedidos mesmo sem esta regra.")
            elif n_mod:
                st.caption(f"O modelo do passo 5 negaria {inteiro(n_mod)} desses {inteiro(n_grupo)} pedidos mesmo sem "
                           "esta regra.")

with st.sidebar.expander("Teto de valor (capacidade de pagamento)"):
    st.checkbox("Limitar pela sobra mensal (entradas − saídas)", key="cap_sobra_on")
    st.slider("Parcela máxima / sobra mensal", 0.10, 0.60, step=0.05, key="cap_sobra", disabled=not ss["cap_sobra_on"])
    st.checkbox("Limitar pela renda declarada", key="cap_renda_on")
    st.slider("Parcela máxima / renda declarada", 0.10, 0.60, step=0.05, key="cap_renda", disabled=not ss["cap_renda_on"])
with st.sidebar.expander("Risco x retorno (modelo)"):
    st.checkbox("Negar quando o resultado esperado for baixo", key="mod_on")
    st.slider("Resultado mínimo esperado por real emprestado", 0.0, 0.08, step=0.005, format="%.3f", key="mod_margem")

atual = aplicar_atual(VERSAO)

st.sidebar.divider()
st.sidebar.caption(f"Dados gerados pelo pipeline em {resumo['gerado_em']}.")
st.sidebar.button("Recarregar dados", on_click=recarregar_dados,
                  help="Lê de novo os arquivos de data/ (por exemplo, depois de rodar python gerar_decisoes.py).")
st.sidebar.divider()
st.sidebar.subheader("Aprovação do analista")
nome = st.sidebar.text_input("Seu nome")
comentario = st.sidebar.text_area("Comentário (opcional)")
confirmado = st.sidebar.checkbox("Revisei o impacto e quero aprovar esta versão")
if st.sidebar.button("Aprovar esta versão da política", type="primary", disabled=not (nome.strip() and confirmado)):
    apv = dec["decisao"] == "APROVADO"
    APROVADA.write_text(json.dumps({
        "aprovado_por": nome.strip(), "aprovado_em": datetime.now().isoformat(timespec="seconds"),
        "comentario": comentario.strip(), "parametros": P,
        "impacto_previsto": {"aprovados": int(apv.sum()), "valor_total": round(float(dec.loc[apv, "valor_aprovado"].sum()), 2),
                             "resultado_esperado_modelo": round(float(dec["ev_modelo"].sum()), 2)},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    st.sidebar.success("Versão gravada em politica_aprovada.json. Rode `python gerar_decisoes.py` para gerar o CSV com ela.")
if APROVADA.exists():
    meta = json.loads(APROVADA.read_text(encoding="utf-8"))
    st.sidebar.caption(f"Versão aprovada (usada na próxima execução do pipeline): aprovada por {meta['aprovado_por']} "
                       f"em {meta['aprovado_em']}.")
    if (datetime.fromisoformat(meta["aprovado_em"]) > datetime.fromisoformat(resumo["gerado_em"])
            or resumo.get("politica_usada") != "politica_aprovada.json"):
        st.sidebar.warning("O arquivo de decisões foi gerado antes desta aprovação: rode python gerar_decisoes.py "
                           "para gerar o CSV com ela.")
else:
    st.sidebar.caption("Nenhuma versão aprovada ainda: o pipeline usa a proposta da IA.")

# ------------------------------------------------------------------ cabeçalho
st.title("Fortuna Crédito · nova política de aprovação")
st.caption("A IA encontrou os padrões e propôs a política; o analista de risco revisa, ajusta e aprova.")
ap_n, ap_a = dec["decisao"] == "APROVADO", atual["decisao"] == "APROVADO"
c = st.columns(4)
dif_ap = int(ap_n.sum() - ap_a.sum())
c[0].metric("Pedidos aprovados", f"{inteiro(ap_n.sum())} de {inteiro(len(dec))}",
            f"{'-' if dif_ap < 0 else '+'}{inteiro(abs(dif_ap))} vs política atual")
c[1].metric("Valor total aprovado", brl(dec.loc[ap_n, "valor_aprovado"].sum()),
            brl_delta(dec.loc[ap_n, "valor_aprovado"].sum() - atual.loc[ap_a, "valor_aprovado"].sum()) + " vs atual")
pd_pond = lambda d, m: float(np.average(d.loc[m, "pd"], weights=d.loc[m, "valor_aprovado"])) if m.any() else np.nan  # noqa: E731
atual_pd = modelo.pd_total(novos[ap_a.values], atual.loc[ap_a, "valor_aprovado"].to_numpy(float))
c[2].metric("Calote esperado dos aprovados", pct(pd_pond(dec, ap_n)),
            f"atual: {pct(float(np.average(atual_pd, weights=atual.loc[ap_a, 'valor_aprovado'])))}", delta_color="off",
            delta_arrow="off")
c[3].metric("Resultado esperado", brl(dec["ev_modelo"].sum()),
            brl_delta(dec["ev_modelo"].sum() - atual["ev_modelo"].sum()) + " vs atual")

aba = st.tabs(["1 · Padrões encontrados", "2 · Política proposta", "3 · Impacto", "4 · Consultar pedido", "5 · Execução"])

# ------------------------------------------------------------------ 1. padrões
with aba[0]:
    st.subheader("O que a IA encontrou no histórico de 10 mil pedidos")
    st.markdown(
        f"Inadimplência média dos contratos aprovados: **{pct(padroes['taxa_media'])}**. Muitos contratos ainda estão "
        "em andamento, e um contrato em dia há 1 mês ainda não provou que é bom pagador. Por isso a taxa conta cada "
        "contrato pela parte do prazo de risco que já passou (o calote sempre começa até 60% do prazo).")
    st.caption("Todos os números abaixo são recalculados pelo código a partir do banco a cada execução.")
    for g in dict.fromkeys(p["grupo"] for p in padroes["padroes"]):
        st.markdown(f"#### {g}")
        for p in [p for p in padroes["padroes"] if p["grupo"] == g]:
            with st.container(border=True):
                a, b = st.columns([4, 1])
                a.markdown(f"**{p['id']}.** {p['titulo']}")
                a.caption(p["leitura"])
                if p["atraso_segmento"] is not None and "atrasam" in p["titulo"]:
                    b.metric("Atraso no grupo", pct(p["atraso_segmento"], 0),
                             f"{(p['atraso_segmento'] - p['atraso_referencia']) * 100:+.0f} p.p.", delta_color="inverse")
                else:
                    b.metric("Inadimplência", pct(p["taxa_segmento"], 0),
                             f"{(p['taxa_segmento'] - p['taxa_referencia']) * 100:+.0f} p.p.", delta_color="inverse")
                with st.expander("Regra técnica, evidência e uso na política"):
                    st.markdown(f"- **Regra:** `{p['regra_tecnica']}`\n"
                                f"- **Histórico:** {inteiro(p['n_hist'])} pedidos no grupo; "
                                f"{inteiro(p['n_aprovados'])} aprovados com desfecho\n"
                                f"- **Verificação:** {p['verificacao']}\n"
                                f"- **Como foi encontrado:** {p['como']}\n"
                                f"- **Uso na política:** {p['acao']}")
    st.markdown("#### Como a base funciona (também descoberto nos dados)")
    for f in padroes["fatos"]:
        st.markdown(f"- **{f['titulo']}.** {f['texto']}")

# ------------------------------------------------------------------ 2. política
with aba[1]:
    st.subheader("Como a nova política decide cada pedido")
    st.caption("Os passos são aplicados nesta ordem. O primeiro que nega encerra a análise.")
    cont = dec["passo"].value_counts()
    st.markdown(f"**1. Dados do bureau.** Consulta a API do bureau, com novas tentativas automáticas quando ela falha "
                f"ou demora. Se continuar indisponível, nega e registra. *Negados: {inteiro(cont.get(1, 0))}.*")
    for passo, titulo, expl in [(2, "Fora da faixa com evidência", "Só aprova onde o histórico tem prova de pagamento "
                                 "(a faixa que o piloto testou). Nega quando:"),
                                (3, "Sinais de alerta", "Padrões que a IA encontrou no histórico. Nega quando:")]:
        st.markdown(f"**{passo}. {titulo}.** {expl}")
        for r in [Regra(**r) for r in P["regras"] if r["passo"] == passo and r["ativa"]]:
            negados = (dec["regra"] == r.id).to_numpy(bool)
            tambem = (f" · o modelo do passo 5 também negaria {inteiro((negados & nega_modelo).sum())}"
                      if passo == 3 and P["usar_modelo"] else "")
            st.markdown(f"   - {texto_regra(r)} · *padrão {r.padrao} · negados: {inteiro(negados.sum())}{tambem}*")
        if passo == 3 and P["usar_modelo"]:
            st.caption("Quando o modelo do passo 5 também negaria os pedidos de uma regra, desligá-la muda só o motivo "
                       "registrado, não a decisão.")
    tetos = []
    if P["teto_parcela_sobre_sobra"] is not None:
        tetos.append(f"a parcela cabe em {P['teto_parcela_sobre_sobra']:.0%} da sobra mensal da conta (entradas menos saídas)")
    if P["teto_comprometimento"] is not None:
        tetos.append(f"a parcela cabe em {P['teto_comprometimento']:.0%} da renda declarada")
    st.markdown(f"**4. Valor pela capacidade de pagamento.** O valor aprovado é o maior valor, até o pedido e até "
                f"R$ 30 mil, em que {' e '.join(tetos) or 'não há teto adicional'}. Se nem R$ 500 cabe, nega. "
                f"*Negados: {inteiro(cont.get(4, 0))}; aprovados com valor reduzido: "
                f"{inteiro((dec['motivo'] == 'aprovado com valor reduzido').sum())}.*")
    diag = modelo.diagnostico["calote"]
    st.markdown(f"**5. Risco x retorno.** Um modelo treinado no histórico estima a chance de calote: risco base de "
                f"**{pct(modelo.pd_base())}**, multiplicado pelos fatores que o cliente tem (tabela abaixo). Com a "
                f"pontuação da Fortuna (+15% em dia, +5% com atraso, −60% calote), um empréstimo só dá lucro se a chance "
                f"de calote ficar abaixo de cerca de 17%. "
                + (f"Nega se o resultado esperado for menor que {pct(P['margem_min'])} do valor. "
                   f"*Negados: {inteiro(cont.get(5, 0))}.*"
                   if P["usar_modelo"] else "*Passo desligado pelo analista.*"))
    fat = pd.DataFrame([{"Fator": FATORES_CALOTE[k][0], "Multiplica o risco por": num(v["rr"], 2),
                         "Intervalo de 95%": f"{num(v['ic95'][0], 2)} a {num(v['ic95'][1], 2)}",
                         "Clientes novos com o fator": inteiro(FATORES_CALOTE[k][1](novos).fillna(False).sum())}
                        for k, v in diag["fatores"].items() if k != "const"])
    st.dataframe(fat, hide_index=True)
    at_d = modelo.diagnostico["atraso"]
    st.caption(f"Atraso: {pct(at_d['taxa_base'])} dos bons pagadores atrasam alguma parcela; "
               + "; ".join(f"{FATORES_ATRASO[k][0]} multiplica a chance de atraso (odds) por {num(v['odds_ratio'], 1)}"
                           for k, v in at_d["fatores"].items())
               + f". Modelo ajustado em {inteiro(diag['n_contratos'])} contratos ({inteiro(diag['calotes'])} calotes).")
    st.markdown(f"**6. Aprovação.** Aprova o valor do passo 4. *Aprovados: {inteiro(cont.get(6, 0))}.*")
    funil = dec["passo"].map(PASSOS).value_counts().reindex(list(PASSOS.values())).fillna(0).rename("pedidos")
    st.bar_chart(funil, horizontal=True)

# ------------------------------------------------------------------ 3. impacto
with aba[2]:
    st.subheader("Nova política x política atual nos 2.000 pedidos novos")
    comp = pd.DataFrame({
        "Política atual": [int(ap_a.sum()), atual.loc[ap_a, "valor_aprovado"].sum(), atual["ev_modelo"].sum()],
        "Nova política": [int(ap_n.sum()), dec.loc[ap_n, "valor_aprovado"].sum(), dec["ev_modelo"].sum()],
    }, index=["Pedidos aprovados", "Valor aprovado (R$)", "Resultado esperado (R$)"])
    st.dataframe(comp.map(inteiro))
    st.caption("Resultado esperado: para cada pedido aprovado, a chance de pagar em dia, com atraso ou não pagar "
               "(modelo de risco, no valor aprovado) vezes +15% / +5% / −60% do valor.")
    st.dataframe(pd.crosstab(atual["decisao"].rename("Política atual"), dec["decisao"].rename("Nova política")).map(inteiro))
    c1, c2 = st.columns(2)
    passa = (ap_n & ~ap_a)
    c1.markdown(f"**A atual nega e a nova aprova ({inteiro(passa.sum())})**")
    motivo_atual = np.select([novos["score"] <= 600, novos["renda_declarada"] <= 2000, novos["restricoes_ativas"] > 0],
                             ["score até 600", "renda até R$ 2.000", "1 restrição ativa"], "outro")
    c1.dataframe(pd.Series(motivo_atual[passa.values]).value_counts().rename("pedidos"))
    c1.caption(f"Resultado esperado desses pedidos: {brl(dec.loc[passa, 'ev_modelo'].sum())}.")
    corta = (~ap_n & ap_a)
    c2.markdown(f"**A atual aprova e a nova nega ({inteiro(corta.sum())})**")
    c2.dataframe(dec.loc[corta, "motivo"].value_counts().rename("pedidos"))
    c2.caption(f"Resultado esperado que a atual teria nesses pedidos: {brl(atual.loc[corta, 'ev_modelo'].sum())}.")

# ------------------------------------------------------------------ 4. pedido
# Como mostrar o valor do cliente em cada coluna usada pelas regras
FORMATO_COLUNA = {"mov_saidas_sobre_entradas": "pct", "outras_sobre_entradas": "pct", "mov_entradas_cv": "pct",
                  "renda_decl_sobre_real": "x", "pedido_sobre_entradas": "x", "renda_declarada": "brl",
                  "restricoes_ativas": "int", "score": "int"}
REGRAS_DURAS_TEXTO = {
    "capacidade": f"parcela acima de {LIMIARES['parcela_sobre_sobra']:.0%} da sobra mensal, ou sem sobra",
    "saidas": f"saídas iguais ou acima de {LIMIARES['saidas_sobre_entradas']:.0%} das entradas",
    "renda_inflada": f"renda declarada mais de {LIMIARES['renda_inflada']:.0f}x as entradas da conta",
}


def valor_do_cliente(coluna: str, v) -> str:
    if pd.isna(v):
        return "—"
    tipo = FORMATO_COLUNA.get(coluna)
    if tipo == "pct":
        return pct(float(v))
    if tipo == "x":
        return f"{num(v, 2)}x"
    if tipo == "brl":
        return brl(float(v))
    if tipo == "int":
        return inteiro(v)
    return num(v, 2)


def explicar_risco(row: pd.DataFrame, d: pd.Series) -> str:
    """Chance de calote do pedido: pelos fatores do modelo ou, se cair numa regra de calote certo, por ela."""
    duras = [k for k, m in regras_duras(row, np.array([d["valor_teto"]], float)).items() if m[0]]
    if duras:
        taxa = max(modelo.taxas_duras[k] for k in duras)
        base = (f"o pedido cai numa regra de calote certo ({'; '.join(REGRAS_DURAS_TEXTO[k] for k in duras)}): "
                f"no histórico, {pct(taxa)} dos contratos aprovados com esse perfil deram calote")
    else:
        base = " × ".join([f"{pct(modelo.pd_base())} (base)"] + [f"{num(m, 2)} ({f})" for f, m in modelo.explicar(row)])
    return (f"{base} → chance de calote **{pct(d['pd'])}**, chance de atraso **{pct(d['p_atraso'])}**, "
            f"resultado esperado **{pct(d['margem'])}** do valor")


with aba[3]:
    st.subheader("Decisão de um pedido, passo a passo")
    idp = st.selectbox("Pedido", dec["id_pedido"].tolist())
    i = int(dec.index[dec["id_pedido"] == idp][0])
    row, d, a = novos.loc[[i]], dec.loc[i], atual.loc[i]
    r0 = row.iloc[0]
    c = st.columns(3)
    c[0].metric("Nova política", d["decisao"], brl(d["valor_aprovado"]) if d["decisao"] == "APROVADO" else None, delta_color="off")
    c[1].metric("Política atual", a["decisao"], brl(a["valor_aprovado"]) if a["decisao"] == "APROVADO" else None, delta_color="off")
    c[2].metric("Valor pedido", brl(r0["valor_solicitado"]), f"{int(r0['prazo_meses'])} parcelas", delta_color="off")
    st.markdown(f"**Motivo:** {d['motivo']}")
    linhas = [{"Passo": 1, "Regra": "dados do bureau", "Valor do cliente": "ok" if pd.notna(r0["score"]) else "indisponível",
               "Resultado": "passa" if pd.notna(r0["score"]) else "NEGA"}]
    for r in sorted([Regra(**r) for r in P["regras"] if r["ativa"]], key=lambda r: r.passo):
        v = r0[r.coluna]
        linhas.append({"Passo": r.passo, "Regra": texto_regra(r), "Valor do cliente": valor_do_cliente(r.coluna, v),
                       "Resultado": "NEGA" if r.mascara(row)[0] else "passa"})
    st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")
    sobra = r0["sobra"]
    st.markdown(f"**Capacidade:** sobra mensal na conta {brl(sobra)}; parcela no valor pedido "
                f"{brl(float(parcela_price(r0['valor_solicitado'], r0['prazo_meses'])))}; valor máximo permitido "
                f"{brl(d['valor_teto'])}.")
    passo_neg = int(d["passo"])
    if passo_neg in (1, 2, 3, 4):   # negado antes do passo 5: o modelo não entrou na decisão
        st.markdown(f"**Risco:** Negado no passo {passo_neg}: a estimativa do modelo não foi usada.")
        if passo_neg > 1:
            st.caption(f"Só para referência (não usada na decisão): {explicar_risco(row, d)}.")
    else:
        st.markdown(f"**Risco:** {explicar_risco(row, d)}.")
    with st.expander("Dados do cliente"):
        campos = ["renda_declarada", "tipo_vinculo", "profissao", "meses_conta", "score", "restricoes_ativas",
                  "parcelas_outras_instituicoes", "consultas_90_dias", "meses_historico_bureau", "mov_meses",
                  "mov_entradas_med", "mov_salario_med", "mov_saidas_med", "mov_entradas_cv", "mov_meses_cheque",
                  "mov_saldo_medio_med"]
        st.dataframe(r0[[c for c in campos if c in r0.index]].rename("valor").astype(str))

# ------------------------------------------------------------------ 5. execução
def frase_bureau(b: dict) -> str:
    """Resiliência do bureau em uma frase (a contagem de tentativas fica no cache e vale para reexecuções)."""
    sem_resposta = sum(b["status"].values()) - b["status"].get("ok", 0)
    tent = {int(k): int(v) for k, v in (b.get("tentativas_por_cliente") or {}).items() if int(v) > 0}
    partes = []
    if tent:
        retry = int(b.get("clientes_com_retry", sum(v for k, v in tent.items() if k > 1)))
        maximo = int(b.get("tentativas_max") or max(tent))
        resp = ("todos responderam" if sem_resposta == 0
                else f"{inteiro(sem_resposta)} ficaram sem resposta e foram negados")
        partes.append(f"Na consulta original: {inteiro(retry)} clientes precisaram de nova tentativa (até {maximo}); {resp}."
                      if retry else f"Na consulta original: nenhum cliente precisou de nova tentativa; {resp}.")
    if b.get("chamadas_http", 0) == 0 and b.get("lidos_do_cache", 0) > 0:
        partes.append("Esta execução leu do cache.")
        if not tent:
            partes.append("O detalhe das tentativas da consulta original não foi registrado (para consultar a API de "
                          "novo: `python gerar_decisoes.py --sem-cache-bureau`).")
    return " ".join(partes)


def frase_validacao(v: dict) -> str:
    """Resultado da validação do CSV em uma frase."""
    frase = "Validação do arquivo"
    if "linhas" in v:
        frase += (f": {inteiro(v['linhas'])} linhas, uma decisão para cada um dos "
                  f"{inteiro(v.get('pedidos_com_decisao', v['linhas']))} pedidos")
        if "aprovados" in v:
            frase += (f"; {inteiro(v['aprovados'])} aprovados e {inteiro(v.get('negados', 0))} negados, "
                      f"{brl(v.get('valor_total_aprovado', 0))} aprovados no total")
    frase += "."
    if v.get("problemas"):
        return frase + " Problemas encontrados: " + "; ".join(v["problemas"]) + "."
    return frase + " Nenhum problema encontrado."


with aba[4]:
    st.subheader("Execução do pipeline")
    st.markdown(f"Gerado em **{resumo['gerado_em']}** · arquivo **{resumo['arquivo']}** · "
                f"{'✅ formato válido' if resumo['validacao'].get('ok') else '❌ problemas no arquivo'} · "
                f"política usada: {resumo['politica_usada']}")
    b = resumo["bureau"]
    c = st.columns(5)
    c[0].metric("Clientes consultados", inteiro(sum(b["status"].values())))
    c[1].metric("Chamadas HTTP nesta execução", inteiro(b["chamadas_http"]))
    c[2].metric("Respostas 503 tratadas nesta execução", inteiro(b["respostas_503"]))
    c[3].metric("Timeouts tratados nesta execução", inteiro(b["timeouts"]))
    c[4].metric("Lidos do cache", inteiro(b["lidos_do_cache"]))
    if frase := frase_bureau(b):
        st.markdown(frase)
    st.caption("Bureau: timeout por chamada, novas tentativas com espera crescente e aleatória em 503/timeout/erro de "
               "conexão, rodadas extras para quem continuou falhando, cache em disco (a resposta de um cliente não muda) "
               "e validação de cada resposta. Cliente sem resposta é negado e registrado.")
    st.markdown(frase_validacao(resumo["validacao"]))
    st.code("python gerar_decisoes.py   # gera dividendos_final.csv do zero", language="bash")
