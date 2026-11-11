"""Gera output/painel.html a partir de output/resumo.json, output/avaliacao.json, output/decisoes_detalhadas.csv
e output/simulador.json (simulador do analista; motor em src/simulador.js e tela em src/simulador_ui.js).

Uso: python gerar_painel.py   (o gerar_decisoes.py já chama no final)
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent
SAIDA = RAIZ / "output"

ROTULOS_FEATURE = {
    "parcela_sobre_sobra": "Parcela ÷ sobra mensal", "t_rel": "Quanto do prazo já passou (o calote se concentra no início)",
    "mov_saidas_sobre_entradas": "Saídas ÷ entradas da conta", "comprometimento": "Parcela ÷ renda declarada",
    "comprometimento_real": "Parcela ÷ entradas reais", "comprometimento_total": "(Parcela + dívidas fora) ÷ renda",
    "mov_entradas_cv": "Instabilidade das entradas", "renda_decl_sobre_real": "Renda declarada ÷ entradas reais",
    "mov_meses_cheque": "Meses no cheque especial", "mov_dias_cheque_total": "Dias no cheque especial",
    "score": "Score do bureau", "consultas_90_dias": "Consultas ao CPF (90 dias)",
    "meses_historico_bureau": "Meses de histórico no bureau", "divida_outras_sobre_renda": "Dívidas fora ÷ renda",
    "renda_declarada": "Renda declarada", "prazo_meses": "Prazo", "mov_saldo_medio_med": "Saldo médio",
    "restricoes_ativas": "Restrições ativas", "vinc_aposentado": "Aposentado", "vinc_assalariado": "Assalariado",
    "vinc_autonomo": "Autônomo", "vinc_empresario": "Empresário",
}


# ---------------------------------------------------------------- formatação pt-BR
def num(v, casas=0):
    s = f"{v:,.{casas}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def brl(v, casas=0):
    sinal = "−" if v < 0 else ""
    return f"{sinal}R$ {num(abs(v), casas)}"


def mi(v):
    a = abs(v)
    if a < 500:
        return "R$ 0"
    sinal = "−" if v < 0 else "+"
    return f"{sinal}R$ {num(a / 1e6, 2)} mi" if a >= 1e6 else f"{sinal}R$ {num(a / 1e3, 0)} mil"


def pct(v, casas=1):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{num(v * 100, casas)}%"


def e(s):
    return html.escape(str(s))


# ---------------------------------------------------------------- blocos
def bloco_padroes(pads, media):
    linhas = []
    for p in pads:
        largura = min(100, p["pd"] * 100)
        n_novos = "—" if p["n_novos"] is None else num(p["n_novos"])
        frase = (f"Clientes {e(p['sujeito'])} têm inadimplência de <b>{pct(p['pd'])}</b>, contra "
                 f"{pct(media)} da média. Afeta <b>{num(p['n'])}</b> clientes no histórico.")
        tip = f"{p['titulo']}: {pct(p['pd'])} de calote (média {pct(media)}) · {num(p['n'])} contratos"
        linhas.append(f"""
      <li class="pad">
        <div class="pad-top"><span class="chip {p['tipo']}">{ {'risco': 'Risco', 'oportunidade': 'Oportunidade', 'neutro': 'Não é sinal'}[p['tipo']] }</span>
          <h4>{e(p['titulo'])}</h4></div>
        <p class="frase">{frase}</p>
        <div class="bar" data-tip="{e(tip)}" role="img" aria-label="{e(tip)}">
          <span class="fill" style="width:{largura:.1f}%"></span>
          <span class="media" style="left:{media * 100:.1f}%"></span>
        </div>
        <p class="meta"><span>{e(p['leitura'])}</span>
          <span class="kv">Nos 2.000 novos pedidos{' (pelo valor pedido)' if p.get('depende_valor') else ''}: <b>{n_novos}</b></span>
          <span class="kv">Atraso entre os que pagam: <b>{pct(p['taxa_atraso'], 0)}</b></span></p>
      </li>""")
    return "\n".join(linhas)


def grafico_oot(oot):
    """Barras agrupadas: calotes observados x previstos por trimestre (modelo treinado até set/2025)."""
    W, H, L, R, T, B = 720, 260, 44, 12, 16, 44
    n = len(oot)
    vmax = max(max(r["calotes_observados"], r["calotes_previstos"]) for r in oot)
    topo = int(np.ceil(vmax / 50.0) * 50)
    cw = (W - L - R) / n
    bw = min(22, cw * 0.32)
    y = lambda v: T + (H - T - B) * (1 - v / topo)  # noqa: E731
    partes = []
    # faixa "fora do treino"
    i0 = next((i for i, r in enumerate(oot) if not r["no_treino"]), n)
    if i0 < n:
        x0 = L + i0 * cw
        partes.append(f'<rect x="{x0:.1f}" y="{T}" width="{W - R - x0:.1f}" height="{H - T - B}" class="faixa"/>')
        partes.append(f'<text x="{x0 + 6:.1f}" y="{T + 12}" class="lbl">fora do treino (inclui o piloto)</text>')
    for v in range(0, topo + 1, 50):
        partes.append(f'<line x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                      f'<text x="{L - 6}" y="{y(v) + 4:.1f}" class="tick" text-anchor="end">{v}</text>')
    for i, r in enumerate(oot):
        cx = L + i * cw + cw / 2
        o, p = r["calotes_observados"], r["calotes_previstos"]
        for k, (val, cls) in enumerate([(o, "s1"), (p, "s2")]):
            x = cx - bw - 1 + k * (bw + 2)
            h = max(0.0, y(0) - y(val))
            if h > 0:
                partes.append(f'<path d="M{x:.1f},{y(0):.1f} V{y(val) + 3:.1f} q0,-3 3,-3 H{x + bw - 3:.1f} q3,0 3,3 V{y(0):.1f} Z" class="{cls}"/>')
        partes.append(f'<text x="{cx:.1f}" y="{H - B + 16}" class="tick" text-anchor="middle">{r["trimestre"]}</text>')
        tip = f'{r["trimestre"]}: {num(o)} calotes observados · {num(p, 1)} previstos · {num(r["contratos"])} contratos'
        partes.append(f'<rect x="{L + i * cw:.1f}" y="{T}" width="{cw:.1f}" height="{H - T - B}" class="hit" data-tip="{e(tip)}"/>')
    partes.append(f'<line x1="{L}" x2="{W - R}" y1="{y(0):.1f}" y2="{y(0):.1f}" class="eixo"/>')
    return (f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Calotes observados e previstos por trimestre">'
            + "".join(partes) + "</svg>")


def tabela(cab, linhas, classes=None):
    th = "".join(f"<th>{c}</th>" for c in cab)
    trs = []
    for ln in linhas:
        tds = "".join(f'<td class="{(classes or {}).get(i, "")}">{c}</td>' for i, c in enumerate(ln))
        trs.append(f"<tr>{tds}</tr>")
    return f'<div class="tbl"><table><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'


SIM_CSS = """
.sim-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; margin-top: 14px; }
.sim-grupo { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; min-width: 0; }
.sim-grupo h3 { margin: 0; font-size: 15px; }
.sim-grupo .sim-cab { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; margin-bottom: 4px; }
.sim-regra { padding: 9px 0 7px; border-top: 1px dashed var(--line); }
.sim-topo { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
.sim-liga { cursor: pointer; }
.sim-liga input { accent-color: var(--accent); }
.sim-regra input[type=range] { width: 100%; accent-color: var(--accent); margin: 6px 0 2px; }
.sim-rot { font-size: 13.5px; }
.sim-regra.off .sim-rot, .sim-regra.off input[type=range] { opacity: .45; }
.sim-regra.mudou .sim-rot { color: var(--warn); font-weight: 600; }
.sim-cnt { font-family: var(--f-mono); font-size: 12px; color: var(--muted); white-space: nowrap; }
.sim-ev { margin-top: 2px; }
.sim-acoes { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; margin: 18px 0 8px; }
.sim-acoes input { font: inherit; padding: 7px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); color: var(--fg); width: 220px; max-width: 100%; }
.callout.aviso { background: var(--risk-bg); }
#sim-mudancas .ok { color: var(--good); } #sim-mudancas .no { color: var(--risk); }
#sim-mudancas button.ex { padding: 2px 8px; font-family: var(--f-mono); }
"""


NOTA_CHEQUE_CONSULTAS = """<p class="small"><b>Mudança depois das respostas da Fortuna (v4).</b> Perguntamos se cheque especial e muitas consultas ao CPF
      deveriam negar o pedido. A Fortuna pediu que a solução respondesse. Os dados dizem que não, sozinhos: todo cliente com 8 ou mais consultas,
      e quase todo cliente com cheque especial em 2 ou mais meses, também gasta mais de 80% do que entra, e essa regra já o nega.
      Desligar as consultas não mudou nenhuma decisão. Desligar o cheque aprovou 6 pedidos, e o resultado esperado subiu pelo modelo e no backtest.
      As duas medidas continuam no modelo do passo 5, e o analista pode religar as regras no simulador.</p>"""


def itens_passo2(P: dict, restr2: int) -> str:
    """Regras do passo 2 que estão ligadas (None = desligada pelo analista)."""
    itens = []
    if P["restricoes_max"] is not None:
        itens.append(f"{P['restricoes_max'] + 1:.0f} ou mais restrições ativas ({num(restr2)} pedidos). "
                     "Ninguém assim foi aprovado no histórico, então não há como medir o risco.")
    faixas = [t for t in (f"score abaixo de {num(P['score_min'])}" if P["score_min"] is not None else "",
                          f"renda abaixo de {brl(P['renda_min'])}" if P["renda_min"] is not None else "") if t]
    if faixas:
        frase = " ou ".join(faixas)
        itens.append(frase[0].upper() + frase[1:] + ", abaixo de qualquer cliente já aprovado.")
    return "".join(f"<li>{t}</li>" for t in itens) or "<li>Nenhuma regra ligada neste passo.</li>"


def itens_passo3(P: dict) -> str:
    """Sinais de alerta que estão ligados (None = desligado)."""
    itens = [
        ("meses_cheque_max", lambda v: f"Cheque especial em {v + 1:.0f} ou mais meses no último ano."),
        ("saidas_sobre_entradas_max", lambda v: f"Saídas acima de {pct(v, 0)} das entradas da conta."),
        ("consultas_90d_max", lambda v: f"{v + 1:.0f} ou mais consultas ao CPF em 90 dias."),
        ("renda_decl_sobre_real_max", lambda v: f"Renda declarada mais que {num(v)} vezes as entradas reais."),
        ("tendencia_entradas_max", lambda v: f"Pico de entradas: os 3 meses antes do pedido vêm {num((v - 1) * 100)}% ou mais "
                                             "acima da média dos meses anteriores."),
        ("pedido_sobre_entradas_max", lambda v: f"Pedido maior que {num(v)} vezes o que entra por mês na conta. Nega em vez de reduzir: "
                                                "no histórico, reduzir o valor não tirou o risco."),
        ("outras_sobre_entradas_max", lambda v: f"Parcelas em outros bancos acima de {pct(v, 0)} do que entra na conta."),
    ]
    lis = "".join(f"<li>{texto(P[k])}</li>" for k, texto in itens if P[k] is not None)
    return lis or "<li>Nenhum sinal de alerta ligado.</li>"


def nota_passo3(P: dict) -> str:
    """Explica o cheque especial e as consultas quando estão desligados (v4)."""
    desligados = [nome for k, nome in (("meses_cheque_max", "cheque especial recorrente"),
                                       ("consultas_90d_max", "muitas consultas ao CPF")) if P[k] is None]
    if not desligados:
        return ""
    if len(desligados) == 2 and P["saidas_sobre_entradas_max"] == 0.80:
        return NOTA_CHEQUE_CONSULTAS
    if P["saidas_sobre_entradas_max"] is not None:
        return (f'<p class="small"><b>Não nega sozinho nesta versão:</b> {" e ".join(desligados)}. É marca de quem gasta mais do que '
                f'{pct(P["saidas_sobre_entradas_max"], 0)} do que entra, que a regra das saídas já nega. Continua no modelo do passo 5.</p>')
    return f'<p class="small"><b>Desligados nesta versão:</b> {" e ".join(desligados)}. Continuam no modelo do passo 5.</p>'


AGENTES_HTML = """
  <h3>Segunda frente: agentes de IA leram o histórico e tentaram derrubar cada achado</h3>
  <p>Em paralelo à varredura, 7 pares de agentes de IA (modelos de linguagem) analisaram o histórico, cada par num tema:
  bureau, movimentação da conta, cadastro e renda, valor e capacidade, atraso e censura, mineração de regras e auditoria da política atual.
  Em cada par, um agente propõe padrões e o outro tenta derrubá-los com os dados. Onde os pares discordaram, uma síntese refez as contas.
  Dois achados dessa frente viraram regra na v3: o pedido excessivo e a dívida medida sobre as entradas reais.</p>
  <div class="tbl"><table>
    <thead><tr><th>Achado dos agentes</th><th>Veredito</th><th>Na política proposta</th></tr></thead>
    <tbody>
      <tr><td>Parcela acima de 50% da sobra mensal: calote quase certo. O degrau fica exatamente em 50%, e o gatilho é o valor <b>aprovado</b>, não o pedido.</td>
        <td>Confirmado</td><td>Passo 4: parcela até 40% da sobra. Reduzir o valor resolve.</td></tr>
      <tr><td>Quem gasta 90% ou mais do que entra na conta: calote quase certo.</td><td>Confirmado</td><td>Passo 3: saídas acima de 80% das entradas.</td></tr>
      <tr><td>Renda declarada maior que 2 vezes as entradas reais. Só aparece em conta nova.</td><td>Confirmado</td><td>Passo 3.</td></tr>
      <tr><td>Pedido maior que 6 vezes as entradas do mês: reduzir o valor não resolve. É isso que explica o erro da política atual ao cortar para 30% da renda declarada:
        os reduzidos que pediram até 6x deram só 12,6% de calote.</td><td>Confirmado; virou regra na v3</td><td>Passo 3: nega em vez de reduzir.</td></tr>
      <tr><td>Dívida em outros bancos acima de 35% das entradas reais. Contra a renda declarada, a mesma conta não separa bons de maus pagadores.</td>
        <td>Confirmado; virou regra na v3</td><td>Passo 3.</td></tr>
      <tr><td>Score não prevê calote. Com menos de 12 meses de histórico no bureau, o score é sorteado entre 450 e 590.</td><td>Confirmado</td>
        <td>Passo 2 aceita score a partir de 450.</td></tr>
      <tr><td>1 restrição ativa aumenta o atraso, não o calote.</td><td>Confirmado</td><td>Aprova; o atraso maior entra no resultado esperado do passo 5.</td></tr>
      <tr><td>Entradas instáveis (variação acima de 35%), só em autônomos e empresários: cerca de 20% de calote.</td><td>Confirmado, no ponto de equilíbrio</td>
        <td>Entra no modelo do passo 5, não como corte.</td></tr>
      <tr><td>8 ou mais consultas ao CPF; cheque especial em 2 ou mais meses.</td><td>Derrubados como regra própria: são marcas do perfil que gasta tudo o que entra</td>
        <td>Na proposta v4, depois das respostas da Fortuna, não negam sozinhos: desligar as consultas não mudou nenhuma decisão, e desligar o cheque especial aprovou 6 pedidos. Continuam no modelo do passo 5.</td></tr>
      <tr><td>CEP iniciado em 1, a partir de abril de 2025: risco cerca de 2 vezes maior.</td><td>Achado, mas <b>não usado</b></td>
        <td>É atributo sensível. Os agentes estimaram que usá-lo renderia só cerca de R$ 300 a mais. Não usamos gênero, CEP, estado civil nem idade.</td></tr>
    </tbody></table></div>
  <details><summary>Como os agentes explicam os dados, e a checagem contra o histórico</summary>
    <ul class="small">
      <li><b>Três situações de calote quase certo:</b> saídas de 90% ou mais das entradas; parcela acima de 50% da sobra mensal; renda declarada acima de 2 vezes as entradas.</li>
      <li><b>Fora delas, o risco parte de cerca de 8% e se multiplica:</b> 4,9 vezes com pedido acima de 6x as entradas; 3,1 vezes com dívida acima de 35% das entradas;
        2,2 vezes com entradas instáveis; 1,4 vez com menos de 36 meses de bureau; 0,73 vez para aposentados.</li>
      <li><b>O calote começa até 60% do prazo.</b> Parcela não paga há mais de 60 dias nunca é paga depois.</li>
      <li><b>Checagem:</b> aplicada aos 6.033 contratos aprovados do histórico, essa explicação prevê 613 calotes; foram 626.</li>
      <li><b>Perguntas que ficaram para o analista:</b> 2 ou mais restrições (174 pedidos novos), que ninguém no histórico teve aprovadas, são a maior aposta pendente;
        o corte exato do pedido excessivo fica entre 5x e 6x.</li>
    </ul>
    <p class="small muted">Os agentes mediram a inadimplência por exposição e em clientes sem os perfis de calote quase certo, por isso algumas taxas diferem das dos cards acima,
    que usam Kaplan-Meier no grupo inteiro. Relatório completo e o roteiro dos agentes em <span class="mono">docs/descoberta_agentes/</span>.</p>
  </details>"""


MUDA_CSS = """
:root { --warn-bg: #fdf1e3; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --warn-bg: #3a2a12; } }
:root[data-theme="dark"] { --warn-bg: #3a2a12; }
.ad-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 16px; }
.ad { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; min-width: 0; }
.ad .k { font-size: 12px; color: var(--muted); }
.ad-v { display: flex; align-items: baseline; flex-wrap: wrap; gap: 2px 10px; font-family: var(--f-mono); font-variant-numeric: tabular-nums; margin-top: 4px; }
.ad-v .antes { font-size: 16px; color: var(--muted); }
.ad-v .seta { color: var(--muted); }
.ad-v .depois { font-size: 26px; font-weight: 500; }
.ad .s { font-size: 12.5px; color: var(--muted); margin-top: 2px; }
.ad.destaque { border-color: var(--accent); }
.ad.destaque .depois, .ad .s b { color: var(--accent); }
.fluxo { display: flex; gap: 2px; height: 34px; border-radius: 6px; overflow: hidden; margin: 10px 0 8px; }
.fluxo span { display: grid; place-items: center; min-width: 3px; font-family: var(--f-mono); font-size: 12.5px; font-weight: 500;
  color: var(--surface); white-space: nowrap; overflow: hidden; }
.f-igual { background: var(--muted); } .f-reduz { background: var(--warn); } .f-nega { background: var(--risk); }
.f-aprova { background: var(--good); } .fluxo span.f-negam { background: var(--band); color: var(--muted); }
.fluxo-leg { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; color: var(--muted); }
.fluxo-leg b { color: var(--fg); font-family: var(--f-mono); font-weight: 500; }
.fluxo-leg i { display: inline-block; width: 12px; height: 12px; border-radius: 3px; vertical-align: -2px; margin-right: 6px; }
.fluxo-leg i.f-negam { background: var(--band); border: 1px solid var(--line); }
.chip.reduz { color: var(--warn); background: var(--warn-bg); }
.mud { display: grid; grid-template-columns: minmax(0, 5fr) minmax(0, 7fr); gap: 12px 28px; background: var(--surface);
  border: 1px solid var(--line); border-left: 4px solid var(--c); border-radius: 8px; padding: 16px 18px; margin-top: 12px; }
.mud.nega { --c: var(--risk); } .mud.aprova { --c: var(--good); } .mud.reduz { --c: var(--warn); }
.mud h3 { margin: 8px 0 4px; font-size: 18px; text-wrap: balance; }
.mud-top { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; }
.mud-n { font-family: var(--f-mono); font-size: 13px; color: var(--muted); white-space: nowrap; }
.mud-nota { margin-top: 16px; }
.mud-n b { color: var(--fg); font-weight: 500; } .mud-n b.g { color: var(--c); }
.mud .porque { margin: 0; }
.mud-linhas { list-style: none; margin: 0; padding: 0; display: grid; align-content: start; font-size: 13.5px; }
.mud-linhas li { display: grid; grid-template-columns: minmax(0, 1fr) 52px 96px 42px; gap: 10px; align-items: center;
  padding: 6px 0; border-bottom: 1px dashed var(--line); }
.mud-linhas li:last-child { border-bottom: 0; }
.mud-linhas li.cab { font-size: 11.5px; color: var(--muted); padding-top: 0; border-bottom: 1px solid var(--line); }
.mud-linhas .q, .mud-linhas .pv { font-family: var(--f-mono); font-variant-numeric: tabular-nums; text-align: right; }
.mud-linhas .bar { height: 8px; } .mud .bar .fill { background: var(--c); }
.mud .rodape { grid-column: 1 / -1; font-size: 12.5px; color: var(--muted); margin: 0; max-width: none; }
:root { --fx0: #1f8a5b; --fx1: #8cc9a8; --fx2: #e8a33d; --fx3: #c8371f; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --fx0: #47cd89; --fx1: #2b6e50; --fx2: #fdb022; --fx3: #f97066; } }
:root[data-theme="dark"] { --fx0: #47cd89; --fx1: #2b6e50; --fx2: #fdb022; --fx3: #f97066; }
.ad-grid { grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); }
.ad-v .depois { flex-basis: 100%; }
.cen { display: grid; gap: 10px; margin-top: 8px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; }
.cen-linha { display: grid; grid-template-columns: minmax(0, 1fr) 96px; gap: 3px 12px; align-items: center; }
.cen-lab { grid-column: 1 / -1; font-size: 13px; font-weight: 600; }
.cen-trilha { position: relative; height: 12px; }
.cen-zero { position: absolute; top: -3px; bottom: -3px; width: 1px; background: var(--fg); opacity: .5; }
.cen-bar { position: absolute; top: 0; bottom: 0; border-radius: 3px; }
.cen-bar.atual { background: var(--muted); } .cen-bar.prop { background: var(--accent); }
.cen-v { font-family: var(--f-mono); font-size: 12.5px; text-align: right; font-variant-numeric: tabular-nums; }
.cen-v.neg { color: var(--risk); }
.fx { display: grid; gap: 8px; margin-top: 8px; }
.fx-linha { display: grid; grid-template-columns: 70px minmax(0, 1fr) 86px; gap: 10px; align-items: center; font-size: 13px; }
.fx-trilha { display: flex; gap: 1px; height: 22px; }
.fx-trilha span:first-child { border-radius: 4px 0 0 4px; } .fx-trilha span:last-child { border-radius: 0 4px 4px 0; }
.fx-v { font-family: var(--f-mono); font-size: 12.5px; text-align: right; }
.fx0 { background: var(--fx0); } .fx1 { background: var(--fx1); } .fx2 { background: var(--fx2); } .fx3 { background: var(--fx3); }
ul.fo { list-style: none; padding: 0; margin: 10px 0; display: grid; gap: 8px; }
ul.fo li { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr) 92px 40px; gap: 12px; align-items: center; font-size: 13.5px; }
.fo-trilha { height: 12px; background: var(--band); border-radius: 3px; position: relative; }
.fo-trilha span { position: absolute; inset: 0 auto 0 0; border-radius: 3px; background: var(--muted); }
ul.fo li.nega .fo-trilha span { background: var(--risk); } ul.fo li.aprova .fo-trilha span { background: var(--good); }
ul.fo li.reduz .fo-trilha span { background: var(--warn); }
.fo-v, .fo-p { font-family: var(--f-mono); font-size: 12.5px; text-align: right; font-variant-numeric: tabular-nums; }
.fo-p { font-weight: 600; }
.fo-call { border-left: 3px solid var(--risk); border-radius: 0 8px 8px 0; }
.fo-call p { max-width: none; }
td.n.neg { color: var(--risk); } td.n.pos { color: var(--good); }
ul.atencao { padding-left: 18px; display: grid; gap: 8px; margin: 8px 0; }
ul.atencao li { max-width: 90ch; }
@media (max-width: 720px) { .mud { grid-template-columns: minmax(0, 1fr); }
  ul.fo li { grid-template-columns: minmax(0, 1fr) 84px 36px; } ul.fo .fo-trilha { grid-column: 1 / -1; grid-row: 2; } }
@media (max-width: 440px) { .mud-linhas li { grid-template-columns: minmax(0, 1fr) 44px 42px; } .mud-linhas .bh, .mud-linhas .bar { display: none; } }
"""


def _pd_padrao(pads: list[dict], trecho: str, tipo: str | None = None):
    """Inadimplência do primeiro padrão cujo título contém o trecho."""
    for p in pads:
        if (tipo is None or p["tipo"] == tipo) and trecho.lower() in p["titulo"].lower():
            return p["pd"]
    return None


# trecho do motivo de negação -> trecho do título do padrão com a inadimplência do grupo
MOTIVO_PADRAO = [("outros bancos", "Dívidas fora acima de 35%"), ("pede mais de", "Pedido acima de"),
                 ("gasta mais de", "Gasto acima de"), ("pico de entradas", "Pico de entradas"),
                 ("renda declarada mais que", "Renda declarada inflada"), ("cheque", "Cheque especial"),
                 ("consultas", "consultas ao CPF")]


def _linha_mud(rotulo: str, qtd, pdv, media: float, tip: str = "") -> str:
    q = "" if qtd is None else num(qtd)
    if pdv is None:
        barra, pv = '<span class="bh"></span>', "—"
    else:
        dica = e(tip or f"{rotulo}: {pct(pdv, 0)} de calote no histórico (média {pct(media, 0)})")
        barra = (f'<span class="bar" data-tip="{dica}"><span class="fill" style="width:{min(100, pdv * 100):.1f}%"></span>'
                 f'<span class="media" style="left:{media * 100:.1f}%"></span></span>')
        pv = pct(pdv, 0)
    return f'<li><span>{e(rotulo)}</span><span class="q">{q}</span>{barra}<span class="pv">{pv}</span></li>'


def _cartao_mud(classe: str, chip: str, titulo: str, d: dict | None, porque: str, linhas: list[str], rodape: str,
                cab_qtd: str = "Pedidos") -> str:
    n = num(d["pedidos"]) if d else "0"
    ganho = mi(d["ganho"]) if d else "R$ 0"
    cab = (f'<li class="cab"><span>Motivo</span><span class="q">{cab_qtd}</span><span class="bh"></span>'
           f'<span class="pv">Calote</span></li>')
    chip_cls = {"nega": "risco", "aprova": "oportunidade", "reduz": "reduz"}[classe]
    return f"""
  <article class="mud {classe}">
    <div><div class="mud-top"><span class="chip {chip_cls}">{chip}</span><span class="mud-n"><b>{n}</b> pedidos · <b class="g">{ganho}</b></span></div>
      <h3>{titulo}</h3><p class="porque">{porque}</p></div>
    <ul class="mud-linhas">{cab}{"".join(linhas)}</ul>
    <p class="rodape">{rodape}</p>
  </article>"""


GANHO_EM_DIA, GANHO_ATRASO, PERDA_CALOTE = 0.15, 0.05, 0.60  # regras do desafio (as mesmas de src/politica.py)
PD_EQUILIBRIO = 0.16  # acima desta chance de calote, emprestar dá prejuízo (de 15,5% a 17,8%, conforme a chance de atraso)
FAIXAS_RISCO = [(0.0, 0.10, "até 10%"), (0.10, 0.16, "10% a 16%"), (0.16, 0.30, "16% a 30%"), (0.30, 1.01, "acima de 30%")]
CENARIOS = [("Previsto", GANHO_ATRASO, 1.0), ("Atraso custa −10%, como a Fortuna estimou", -0.10, 1.0),
            ("Calote 20% maior que o previsto", GANHO_ATRASO, 1.2), ("Calote 50% maior", GANHO_ATRASO, 1.5),
            ("Calote dobra", GANHO_ATRASO, 2.0)]


def curto(v: float) -> str:
    """R$ em mi ou mil, sem sinal de mais (para estoques: valor emprestado, perda)."""
    sinal, a = ("−" if v < 0 else ""), abs(v)
    return f"{sinal}R$ {num(a / 1e6, 2)} mi" if a >= 1e6 else f"{sinal}R$ {num(a / 1e3, 0)} mil"


def _atraso_por_pedido(r: dict, det: pd.DataFrame) -> pd.Series:
    """Chance de atrasar entre os que pagam, para todos os pedidos (o arquivo de decisões só traz para quem chegou ao passo 5)."""
    a = det["p_atraso"].copy()
    caminho = SAIDA / "simulador.json"
    if caminho.exists():
        s = json.loads(caminho.read_text(encoding="utf-8"))["pedidos"]
        a = det["id_pedido"].map(dict(zip(s["id"], s["atraso"]))).fillna(a)
    return a.fillna(r["taxa_atraso"]["sem_restricao"]).astype(float)


def _lucro(v, p, a, atraso=GANHO_ATRASO, k=1.0) -> float:
    margem = GANHO_EM_DIA * (1 - a) + atraso * a
    q = np.minimum(k * p, 1.0)
    return float((v * ((1 - q) * margem - PERDA_CALOTE * q)).sum())


def numeros_carteira(r: dict, det: pd.DataFrame) -> tuple[dict, pd.Series]:
    """Dinheiro e risco das carteiras que cada política aprova nos pedidos novos, pelo modelo.

    A chance de calote da política atual, no valor que ela aprova, sai do resultado esperado que o pipeline calculou para ela
    (o resultado esperado é linear na chance de calote, então dá para inverter)."""
    a_ = _atraso_por_pedido(r, det)
    m = GANHO_EM_DIA * (1 - a_) + GANHO_ATRASO * a_
    with np.errstate(divide="ignore", invalid="ignore"):
        pd_atual = (m - det["ev_atual"] / det["valor_atual"]) / (m + PERDA_CALOTE)
    cart = {}
    for nome, sel, v, p in (("atual", det["decisao_atual"] == "APROVADO", det["valor_atual"], pd_atual),
                            ("proposta", det["decisao"] == "APROVADO", det["valor_aprovado"], det["pd"])):
        v, p, a = v[sel].to_numpy(float), p[sel].to_numpy(float), a_[sel].to_numpy(float)
        mm = GANHO_EM_DIA * (1 - a) + GANHO_ATRASO * a
        cart[nome] = dict(
            valor=v.sum(), calote=(v * p).sum() / v.sum(), contratos_calote=p.sum(), perda=(v * p * PERDA_CALOTE).sum(),
            lucro=_lucro(v, p, a), equilibrio=(v * mm).sum() / (v * p * (mm + PERDA_CALOTE)).sum(),
            cenarios=[_lucro(v, p, a, at, k) for _, at, k in CENARIOS],
            faixas=[(v[(p >= lo) & (p < hi)].sum(), int(((p >= lo) & (p < hi)).sum())) for lo, hi, _ in FAIXAS_RISCO])
    return cart, pd_atual


def bloco_cenarios(cart: dict) -> str:
    """Lucro das duas carteiras em cenários piores que o previsto."""
    ca, cp = cart["atual"], cart["proposta"]
    vals = ca["cenarios"] + cp["cenarios"]
    neg, pos = max(0.0, -min(vals)), max(0.0, max(vals))
    escala = (neg + pos) * 1.04 or 1.0
    zero = neg / escala * 100

    def barra(v, cls, quem):
        w = abs(v) / escala * 100
        x = zero if v >= 0 else zero - w
        return (f'<div class="cen-trilha"><span class="cen-zero" style="left:{zero:.1f}%"></span>'
                f'<span class="cen-bar {cls}" style="left:{x:.1f}%;width:{w:.1f}%" data-tip="{e(quem)}: {mi(v)}"></span></div>'
                f'<span class="cen-v{" neg" if v < 0 else ""}">{mi(v)}</span>')

    linhas = "".join(
        f'<div class="cen-linha"><div class="cen-lab">{e(nome)}</div>'
        f'{barra(ca["cenarios"][i], "atual", "Política atual")}{barra(cp["cenarios"][i], "prop", "Proposta")}</div>'
        for i, (nome, _, _) in enumerate(CENARIOS))
    folga = cp["equilibrio"] - 1
    frase_atual = ("A atual já está no zero: qualquer piora vira prejuízo." if ca["equilibrio"] < 1.05
                   else f"A atual aguenta o calote subir {pct(ca['equilibrio'] - 1, 0)} antes de dar prejuízo.")
    return f"""
  <h3>E se o cenário piorar?</h3>
  <p>{frase_atual} A proposta só dá prejuízo se o calote passar de <b>{num(cp['equilibrio'], 1)} vezes</b> o previsto
  (folga de {pct(folga, 0)}).</p>
  <div class="legend"><span><i class="sw" style="background:var(--muted)"></i>Política atual</span><span><i class="sw" style="background:var(--accent)"></i>Proposta</span>
    <span>lucro esperado em cada cenário</span></div>
  <div class="cen">{linhas}</div>"""


def bloco_faixas(cart: dict) -> str:
    """Quanto dinheiro cada carteira põe em cada faixa de chance de calote."""
    vmax = max(cart["atual"]["valor"], cart["proposta"]["valor"])

    def linha(nome, c):
        segs = "".join(
            f'<span class="fx{k}" style="width:{v / vmax * 100:.2f}%" data-tip="{e(nome)}, chance de calote {rot}: {curto(v)} em {num(n)} contratos"></span>'
            for k, ((v, n), (_, _, rot)) in enumerate(zip(c["faixas"], FAIXAS_RISCO)) if v > 0)
        return f'<div class="fx-linha"><span class="fx-lab">{nome}</span><div class="fx-trilha">{segs}</div><span class="fx-v">{curto(c["valor"])}</span></div>'

    def acima(c):
        v = sum(f[0] for f, (lo, _, _) in zip(c["faixas"], FAIXAS_RISCO) if lo >= PD_EQUILIBRIO)
        n = sum(f[1] for f, (lo, _, _) in zip(c["faixas"], FAIXAS_RISCO) if lo >= PD_EQUILIBRIO)
        return v, n
    va, na = acima(cart["atual"])
    vp, np_ = acima(cart["proposta"])
    prop = "nada" if vp < 500 else f"{curto(vp)} ({num(np_)} contrato{'s' if np_ != 1 else ''})"
    leg = "".join(f'<span><i class="sw fx{k}"></i>{rot}</span>' for k, (_, _, rot) in enumerate(FAIXAS_RISCO))
    return f"""
  <h3>Onde está o dinheiro</h3>
  <p>Acima de cerca de {pct(PD_EQUILIBRIO, 0)} de chance de calote, emprestar dá prejuízo. A atual põe <b>{curto(va)}</b> ({num(na)} contratos) nessa faixa.
  A proposta, {prop}.</p>
  <div class="legend"><span>Chance de calote de cada contrato:</span>{leg}</div>
  <div class="fx">{linha("Atual", cart["atual"])}{linha("Proposta", cart["proposta"])}</div>"""


def _rotulo_motivo(motivo: str) -> str:
    rot = re.sub(r"\s*\(.*\)$", "", motivo)
    if motivo.startswith("risco de calote alto"):
        return "Nega por risco alto no modelo, mesmo com valor menor"
    return ("Nega quem " if rot.split()[0] in ("pede", "gasta") else "Nega: ") + rot


def fontes_do_ganho(r: dict, det: pd.DataFrame) -> list[dict]:
    """Ganho sobre a atual separado por regra. Soma exatamente o ganho total.

    Negados que a atual aprovava: cada um conta para a regra que o negou (a primeira, na ordem dos passos)."""
    ap, pp = det["decisao_atual"] == "APROVADO", det["decisao"] == "APROVADO"
    itens = [dict(tipo="nega", motivo=m, rotulo=_rotulo_motivo(m), n=len(t), ganho=float(-t["ev_atual"].sum()))
             for m, t in det[ap & ~pp].groupby("motivo")]
    novos = det[~ap & pp]
    itens.append(dict(tipo="aprova", rotulo="Aprova bom pagador que a atual nega", n=len(novos), ganho=float(novos["ev_modelo"].sum())))
    ambas = det[ap & pp]
    itens.append(dict(tipo="reduz", rotulo="Empresta menos quando a parcela não cabe na sobra",
                      n=int((ambas["valor_aprovado"] < ambas["valor_atual"] - 0.005).sum()),
                      ganho=float((ambas["ev_modelo"] - ambas["ev_atual"]).sum())))
    return sorted(itens, key=lambda x: -x["ganho"])


def bloco_fontes(r: dict, det: pd.DataFrame, pd_atual: pd.Series) -> str:
    """De onde vem o ganho, regra a regra, e por que a maior fatia é tão grande."""
    itens = fontes_do_ganho(r, det)
    total = sum(i["ganho"] for i in itens)
    grandes = [i for i in itens if i["ganho"] >= 0.05 * total]
    resto = [i for i in itens if i["ganho"] < 0.05 * total]
    if resto:
        grandes.append(dict(tipo="resto", rotulo=f"Outras {len(resto)} regras", n=sum(i["n"] for i in resto),
                            ganho=sum(i["ganho"] for i in resto), dica="; ".join(f"{i['rotulo']}: {mi(i['ganho'])}" for i in resto)))
    gmax = max(abs(i["ganho"]) for i in grandes)
    linhas = "".join(
        f'<li class="{i["tipo"]}"><span class="fo-lab">{e(i["rotulo"])}<span class="muted"> · {num(i["n"])} pedidos</span></span>'
        f'<span class="fo-trilha" data-tip="{e(i.get("dica") or i["rotulo"])}"><span style="width:{abs(i["ganho"]) / gmax * 100:.1f}%"></span></span>'
        f'<span class="fo-v">{mi(i["ganho"])}</span><span class="fo-p">{pct(i["ganho"] / total, 0)}</span></li>'
        for i in grandes)

    # a maior fatia: por que rende tanto, e se é erro
    top = itens[0]
    explica = ""
    if top["tipo"] == "nega" and top["ganho"] / total >= 0.25:
        sel = (det["decisao_atual"] == "APROVADO") & (det["decisao"] == "NEGADO") & (det["motivo"] == top["motivo"])
        t = det[sel]
        pd_mod = float((t["valor_atual"] * pd_atual[sel]).sum() / t["valor_atual"].sum())
        chave = next((p for m, p in MOTIVO_PADRAO if m in top["motivo"]), None)
        hist = next((p for p in r["padroes"] if chave and chave.lower() in p["titulo"].lower()), None)
        cortado = t["valor_atual"].mean() < t["valor_solicitado"].mean() - 1
        atual_faz = (f"A atual corta para {brl(t['valor_atual'].mean())}, para a parcela caber em 30% da renda declarada, e aprova."
                     if cortado else "A atual aprova.")
        hist_txt = f" No histórico, clientes assim deram <b>{pct(hist['pd'], 0)}</b> de calote ({num(hist['n'])} contratos)." if hist else ""
        concorda = hist is not None and hist["pd"] > PD_EQUILIBRIO and pd_mod > PD_EQUILIBRIO
        regra_top = next((k for m, k in MOTIVO_REGRA if m in top["motivo"]), None)
        explica = f"""
  <div class="callout fo-call">
    <p><b>Por que {num(top['n'])} pedidos rendem {pct(top['ganho'] / total, 0)} do ganho?</b> São pedidos grandes: {brl(t['valor_solicitado'].mean())} em média.
    {atual_faz} Mesmo assim, o modelo estima <b>{pct(pd_mod, 0)}</b> de chance de calote.{hist_txt}
    Cada um custa em média {brl(top['ganho'] / top['n'])} de prejuízo esperado.</p>
    <p id="fo-erro" data-regra="{e(regra_top or '')}"><b>É erro?</b> {"Não. No valor que a atual aprova, o modelo e o histórico concordam que esse cliente dá prejuízo." if concorda else "O modelo e o histórico não concordam: vale conferir no simulador."}
    O analista pode testar outros cortes no <a href="#simulador">simulador</a>.</p>
  </div>"""
    return f"""
  <h3>De onde vem o lucro</h3>
  <p>O ganho de <b>{mi(total)}</b> sobre a atual, por regra. Cada pedido que muda de decisão conta para a primeira regra que o decidiu.</p>
  <ul class="fo">{linhas}</ul>
  {explica}
  {bloco_sem_regra(r)}"""


MOTIVO_REGRA = [("pede mais de", "pedido_sobre_entradas_max"), ("gasta mais de", "saidas_sobre_entradas_max"),
                ("outros bancos", "outras_sobre_entradas_max"), ("pico de entradas", "tendencia_entradas_max"),
                ("renda declarada mais que", "renda_decl_sobre_real_max"), ("cheque", "meses_cheque_max"),
                ("consultas", "consultas_90d_max")]


def bloco_sem_regra(r: dict) -> str:
    """Quanto o lucro muda se o analista tirar cada regra. A página calcula com o motor do simulador (sem servidor)."""
    if not (SAIDA / "simulador.json").exists():
        return ""
    P = r["parametros"]
    rot = {"pedido_sobre_entradas_max": lambda v: f"Negar pedido acima de {num(v)}x o que entra por mês",
           "saidas_sobre_entradas_max": lambda v: f"Negar gasto acima de {pct(v, 0)} do que entra",
           "outras_sobre_entradas_max": lambda v: f"Negar dívida em outros bancos acima de {pct(v, 0)} do que entra",
           "tendencia_entradas_max": lambda v: "Negar pico de entradas antes do pedido",
           "renda_decl_sobre_real_max": lambda v: f"Negar renda declarada acima de {num(v)}x as entradas",
           "meses_cheque_max": lambda v: f"Negar cheque especial em {v + 1:.0f} ou mais meses",
           "consultas_90d_max": lambda v: f"Negar {v + 1:.0f} ou mais consultas ao CPF"}
    testes = [[k, f(P[k]), None] for k, f in rot.items() if P.get(k) is not None]
    if P["score_min"] is not None and P["score_min"] < 600:
        testes.append(["score_min", f"Aprovar score de {num(P['score_min'])} a 600", 600])
    if P["renda_min"] is not None and P["renda_min"] < 2000:
        testes.append(["renda_min", f"Aprovar renda declarada de {brl(P['renda_min'])} a R$ 2.000", 2000])
    if P["restricoes_max"] is not None and P["restricoes_max"] >= 1:
        testes.append(["restricoes_max", "Aprovar quem tem restrição no nome", 0])
    return f"""
  <h3>E se tirar cada regra?</h3>
  <p>Tirando uma regra de cada vez, sem mexer nas outras. "Se o histórico se repetir" supõe que os clientes liberados deem o calote que
  clientes iguais deram no histórico.</p>
  <div id="fo-sem" data-testes="{e(json.dumps(testes, ensure_ascii=False))}"><p class="small muted">Calculando…</p></div>
  <p class="small"><b>Como ler.</b> As regras de alerta funcionam como seguro. Pelo modelo, tirar uma delas quase não muda o lucro, porque os passos 4 e 5
  negariam ou cortariam a maioria desses pedidos. Elas protegem contra o modelo errar nesses grupos, como o histórico indica.
  Aprovar quem a atual nega rende de fato: sem essas mudanças, o lucro cai pelos dois critérios.</p>"""


SEM_REGRA_JS = r"""
(function () {
  const el = document.getElementById("fo-sem"), dadosEl = document.getElementById("sim-dados");
  if (!el || !dadosEl || !window.Simulador) return;
  const S = window.Simulador, D = JSON.parse(dadosEl.textContent), g = S.decodificarGrade(D.grade_pd_u16_b64);
  const pad = { ...D.parametros_padrao }, base = S.resumir(D, S.simular(D, g, pad), pad);
  const fmt = (v, c) => v.toLocaleString("pt-BR", { minimumFractionDigits: c, maximumFractionDigits: c });
  const mil = v => { const a = Math.abs(v); if (a < 500) return "R$ 0"; const s = v < 0 ? "−" : "+";
    return a >= 1e6 ? `${s}R$ ${fmt(a / 1e6, 2)} mi` : `${s}R$ ${fmt(Math.round(a / 1e3), 0)} mil`; };
  const sem = s => s.replace(/^[+−]/, "");
  const linhas = JSON.parse(el.dataset.testes).map(([id, rot, valor]) => {
    const P = { ...pad, [id]: valor }, r = S.resumir(D, S.simular(D, g, P), P);
    return { id, rot, n: r.aprovados - base.aprovados, mod: r.ganho - base.ganho, hist: r.ganhoHistorico - base.ganho };
  });
  const cls = v => (v <= -500 ? "neg" : v >= 500 ? "pos" : "");
  const esc = s => String(s).replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
  el.innerHTML = `<div class="tbl"><table><thead><tr><th>Se tirar</th><th>Aprovados</th><th>Lucro, pelo modelo</th>
    <th>Lucro, se o histórico se repetir</th></tr></thead><tbody>` + linhas.map(l => `<tr><td>${esc(l.rot)}</td>
    <td class="n">${l.n > 0 ? "+" : ""}${fmt(l.n, 0)}</td><td class="n ${cls(l.mod)}">${mil(l.mod)}</td>
    <td class="n ${cls(l.hist)}">${mil(l.hist)}</td></tr>`).join("") + "</tbody></table></div>";
  const p = document.getElementById("fo-erro");
  const l = p && linhas.find(x => x.id === p.dataset.regra);
  const ev = l && D.evidencia[l.id] && D.evidencia[l.id].grupo_padrao;
  if (l && ev && ev.pd != null && l.hist < l.mod - 500) {
    p.innerHTML = `<b>É erro?</b> Não, mas aqui o modelo e o histórico discordam. Sem essa regra, os passos 4 e 5 emprestariam um valor menor
      a esses clientes, e o modelo acha que aí eles pagam: o lucro pelo modelo ${l.mod >= 500 ? "até sobe " + mil(l.mod) : "fica em " + mil(l.mod)}.
      No histórico, porém, o calote desse grupo passou de <b>${fmt(Math.floor(ev.pd * 10) * 10, 0)}%</b>.
      Se isso se repetir, tirar a regra custa <b>${sem(mil(l.hist))}</b>. A regra é um seguro:
      ${l.mod >= 500 ? "deixa de ganhar " + sem(mil(l.mod)) + " se o modelo estiver certo e " : ""}evita ${sem(mil(l.hist))} de prejuízo se o histórico estiver.
      Ficamos com o histórico. O analista pode testar outros cortes no <a href="#simulador">simulador</a>.`;
  }
})();
"""


def bloco_atencao(r: dict, det: pd.DataFrame, cart: dict, pd_atual: pd.Series) -> str:
    """O que pode dar errado, para quem decide: incerteza do modelo, clientes novos, custo do atraso, regras sem evidência."""
    av_path = SAIDA / "avaliacao.json"
    av = json.loads(av_path.read_text(encoding="utf-8")) if av_path.exists() else None
    itens = []
    if av:
        bt = {x["cfg"]: x for x in av["backtest"]}
        bt_txt = f". Em 10 mil pedidos antigos, decididos por modelos que não os viram, rendeu {mi(bt['proposta']['ganho_vs_atual'])} sobre a atual" if "proposta" in bt else ""
        itens.append(("Os números são uma estimativa do modelo.",
                      f"Ele foi testado em pedidos que não viu: previu bem os calotes dos trimestres seguintes (nota {num(av['fora_do_tempo']['auc'], 2)}, numa escala de 0,5 a 1){bt_txt}."))
    novos = det[(det["decisao_atual"] == "NEGADO") & (det["decisao"] == "APROVADO")]
    piloto = next((g for g in r["onde_atual_erra"] if "a proposta aprova" in g["grupo"]), None)
    itens.append((f"{num(len(novos))} clientes que a Fortuna hoje não atende ({curto(novos['valor_aprovado'].sum())}).",
                  (f"No piloto, clientes assim, sem sinal de alerta, deram {pct(piloto['pd'], 1)} de calote ({num(piloto['n'])} contratos). " if piloto else "")
                  + "Sugestão: acompanhar as primeiras parcelas desse grupo."))
    ca, cp = cart["atual"], cart["proposta"]
    itens.append(("O atraso pode custar mais que o manual diz.",
                  f"A Fortuna estimou −10% no atraso, e não +5%. Nesse caso o lucro da proposta cai para {mi(cp['cenarios'][1])}, e a atual vai a {mi(ca['cenarios'][1])}. "
                  f"A vantagem sobre a atual fica em {mi(cp['cenarios'][1] - ca['cenarios'][1])}."))
    # regra em que o modelo vê empate, mas o histórico vê prejuízo: o ganho real tende a ser maior que o mostrado
    for m, t in det[(det["decisao_atual"] == "APROVADO") & (det["decisao"] == "NEGADO")].groupby("motivo"):
        chave = next((p for k, p in MOTIVO_PADRAO if k in m), None)
        hist = next((p for p in r["padroes"] if chave and chave.lower() in p["titulo"].lower()), None)
        pm = float(pd_atual[t.index].mean())
        if hist and pm < PD_EQUILIBRIO + 0.01 and hist["pd"] > PD_EQUILIBRIO + 0.08:
            itens.append((f"{_rotulo_motivo(m).replace('Nega: ', '').capitalize()}: o modelo e o histórico discordam.",
                          f"O modelo vê esses {num(len(t))} pedidos quase no empate ({pct(pm, 0)} de chance de calote). No histórico, foram {pct(hist['pd'], 0)}. "
                          "Ficamos com o histórico. Se ele estiver certo, o ganho real é maior que o mostrado."))
    restr2 = next((p["pedidos"] for p in r["por_passo"] if p["motivo"].startswith("2+ restrições")), 0)
    if restr2:
        itens.append((f"{num(restr2)} pedidos com 2 ou mais restrições continuam negados.",
                      "Ninguém assim foi aprovado no histórico, então não dá para medir o risco. Pode haver bom pagador aí. "
                      "Sugestão: um piloto pequeno e controlado para medir."))
    lis = "".join(f"<li><b>{e(t)}</b> {d}</li>" for t, d in itens)
    return f"""
  <h3>Pontos de atenção</h3>
  <ul class="atencao">{lis}</ul>"""


PITCH_CSS = """
.pitch h2 { font-size: clamp(26px, 3.6vw, 36px); line-height: 1.15; margin: 0 0 4px; }
.pitch .sub { color: var(--muted); margin: 0 0 14px; }
.big-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.big { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px 18px; min-width: 0; }
.big .k { font-size: 13px; color: var(--muted); }
.big .v { font-family: var(--f-mono); font-size: clamp(30px, 4vw, 40px); font-weight: 500; line-height: 1.15; font-variant-numeric: tabular-nums; }
.big .s { font-size: 13px; color: var(--muted); }
.big.destaque { border: 2px solid var(--accent); } .big.destaque .v { color: var(--accent); }
.pq-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 12px; margin-top: 12px; }
.pq { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px 18px; min-width: 0; }
.pq h3 { margin: 0 0 6px; font-size: 16px; }
.pq ol { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.pq li { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 12px; align-items: start; font-size: 14px; line-height: 1.45;
  padding-top: 10px; border-top: 1px solid var(--line); }
.pq li:first-child { border-top: 0; padding-top: 0; }
.pq li .t { display: block; font-size: 15px; font-weight: 700; }
.pq li .ev b { color: var(--fg); }
.pq li .ev { color: var(--muted); }
.pq .rs { font-family: var(--f-mono); font-size: 13.5px; font-weight: 600; white-space: nowrap; color: var(--good); }
.pq .rs.neg { color: var(--risk); }
.fontes { margin-top: 12px; background: var(--band); border-radius: 10px; padding: 10px 16px; font-size: 13px; }
.fontes b { margin-right: 6px; }
.fontes ul { list-style: none; display: inline; padding: 0; margin: 0; }
.fontes li { display: inline; }
.fontes li + li::before { content: " · "; color: var(--muted); }
details.det-resumo { margin-top: 18px; }
details.det-resumo > summary { font-size: 14px; font-weight: 600; padding: 8px 0; }
"""


def bloco_pitch(r: dict, det: pd.DataFrame, cart: dict) -> str:
    """Uma tela para mostrar ao cliente: resultado, por quê, riscos e de onde vêm os números."""
    P, pads = r["parametros"], r["padroes"]
    media = r["padroes_ref"]["pd_media"]
    dec = {d["grupo"]: d for d in r["decomposicao"]}
    ca, cp = cart["atual"], cart["proposta"]
    at, pr = r["atual"], r["proposta"]
    g = lambda grupo: dec.get(grupo, {}).get("ganho", 0.0)  # noqa: E731

    # por quê 1: as duas regras de negação que mais rendem, com o calote do histórico
    fontes = [i for i in fontes_do_ganho(r, det) if i["tipo"] == "nega" and not i["motivo"].startswith("risco")]
    exemplos = []
    for i in fontes[:2]:
        chave = next((p for m, p in MOTIVO_PADRAO if m in i["motivo"]), None)
        pdh = _pd_padrao(pads, chave, "risco") if chave else None
        rot = re.sub(r"\s*\(.*\)$", "", i["motivo"]).replace(" na conta", "")
        if pdh is not None:
            exemplos.append((("quem " if rot.split()[0] in ("pede", "gasta") else "") + rot, pdh))
    if len(exemplos) == 2:
        ev1 = (f"Quem {exemplos[0][0].removeprefix('quem ')} deu <b>{pct(exemplos[0][1], 0)}</b> de calote no histórico; "
               f"quem {exemplos[1][0].removeprefix('quem ')}, <b>{pct(exemplos[1][1], 0)}</b>. A regra atual aprova os dois.")
    else:
        ev1 = "Sinais no extrato da conta que, no histórico, deram de 27% a 98% de calote. A regra atual aprova esses clientes."

    quem = [t for t in (f"score de {num(P['score_min'])} a 600" if P["score_min"] is not None and P["score_min"] < 600 else "",
                        f"renda de {brl(P['renda_min'])} a R$ 2.000" if P["renda_min"] is not None and P["renda_min"] < 2000 else "",
                        "1 restrição no nome" if P["restricoes_max"] is not None and P["restricoes_max"] >= 1 else "") if t]
    piloto = next((x for x in r["onde_atual_erra"] if "a proposta aprova" in x["grupo"]), None)
    quem_txt = ", ".join(quem[:-1]) + " ou " + quem[-1] if len(quem) > 1 else (quem[0] if quem else "clientes")
    ev2 = (quem_txt[:1].upper() + quem_txt[1:] + ", sem sinal de alerta"
           + (f": no piloto, <b>{pct(piloto['pd'], 1)}</b> de calote, contra {pct(media, 0)} da média." if piloto else "."))
    p50 = _pd_padrao(pads, "acima de 50% da sobra")
    ev3 = (f"A parcela fica em até {pct(P['teto_parcela_sobre_sobra'], 0)} do que sobra na conta no mês."
           + (f" Acima de 50%, <b>{pct(p50, 0)}</b> deram calote." if p50 else ""))

    def item(titulo, ev, valor):
        cls = " neg" if valor < 0 else ""
        return f'<li><span><span class="t">{titulo}</span><span class="ev">{ev}</span></span><span class="rs{cls}">{mi(valor)}</span></li>'

    porque = (item("Nega quem não consegue pagar.", ev1, g("A atual aprova, a proposta nega"))
              + item("Aprova bom pagador que a regra atual recusa.", ev2, g("A atual nega, a proposta aprova"))
              + item("Empresta o que cabe no bolso.", ev3, g("As duas aprovam, a proposta reduz o valor")))

    # riscos: o resultado se sustenta em cenários piores
    i_dobra = next(i for i, c in enumerate(CENARIOS) if c[2] == 2.0)
    i_atr = next(i for i, c in enumerate(CENARIOS) if c[1] < 0)
    novos = det[(det["decisao_atual"] == "NEGADO") & (det["decisao"] == "APROVADO")]
    riscos = (item("E se o calote for o dobro do previsto?",
                   f"A proposta {'ainda lucra' if cp['cenarios'][i_dobra] > 0 else 'perde'}. A regra atual perderia {curto(-ca['cenarios'][i_dobra])}.",
                   cp["cenarios"][i_dobra])
              + item("E se o atraso custar −10%, como a Fortuna estimou?",
                     f"Continua no lucro. A regra atual vai a {mi(ca['cenarios'][i_atr])}.", cp["cenarios"][i_atr])
              + f'<li><span><span class="t">{num(len(novos))} clientes que a Fortuna hoje não atende.</span><span class="ev">'
                f'São {curto(novos["valor_aprovado"].sum())}. Acompanhar as primeiras parcelas desse grupo. '
                f'O analista liga, desliga ou ajusta cada regra no simulador antes de aprovar.</span></span><span></span></li>')

    av_path = SAIDA / "avaliacao.json"
    av = json.loads(av_path.read_text(encoding="utf-8")) if av_path.exists() else None
    fontes_txt = [f"{num(r['alvo']['contratos_aprovados'])} contratos reais, com 6 meses de piloto"]
    if av:
        fontes_txt.append(f"modelo testado em trimestres que nunca viu: previsto e real batem (nota {num(av['fora_do_tempo']['auc'], 2)})")
        bt = {x["cfg"]: x for x in av["backtest"]}
        if "proposta" in bt:
            fontes_txt.append(f"em 10 mil pedidos antigos, {mi(bt['proposta']['ganho_vs_atual'])} sobre a regra atual")
    fontes_txt += ["regra atual reproduzida: acerta 100% das 8.737 decisões dela",
                   "sem CEP, gênero, idade ou estado civil"]

    return f"""
  <div class="pitch">
    <h2>Mais crédito, metade do calote.</h2>
    <p class="sub">A nova política nos {num(r['csv']['linhas'])} pedidos de outubro de 2026, comparada com a regra atual da Fortuna.</p>
    <div class="big-grid">
      <div class="big destaque"><div class="k">Lucro a mais que a regra atual</div><div class="v">{mi(r['ganho_estimado'])}</div>
        <div class="s">a regra atual fica no zero ({mi(ca['lucro'])})</div></div>
      <div class="big"><div class="k">Calote</div><div class="v">{pct(cp['calote'])}</div>
        <div class="s">era {pct(ca['calote'])} do dinheiro emprestado</div></div>
      <div class="big"><div class="k">Crédito liberado</div><div class="v">{curto(cp['valor'])}</div>
        <div class="s">{mi(cp['valor'] - ca['valor'])} · {num(pr['aprovados'])} aprovados (eram {num(at['aprovados'])})</div></div>
    </div>
    <div class="pq-grid">
      <div class="pq"><h3>Por que dá mais lucro</h3><ol>{porque}</ol></div>
      <div class="pq"><h3>Riscos, e por que o resultado se sustenta</h3><ol>{riscos}</ol></div>
    </div>
    <div class="fontes"><b>De onde vêm os números:</b><ul>{"".join(f"<li>{t}</li>" for t in fontes_txt)}</ul></div>
  </div>"""


def bloco_o_que_muda(r: dict, det: pd.DataFrame) -> str:
    """Topo do painel para o cliente: antes e depois, para onde vão os pedidos e as três mudanças com o motivo."""
    P, pads = r["parametros"], r["padroes"]
    media = r["padroes_ref"]["pd_media"]
    dec = {d["grupo"]: d for d in r["decomposicao"]}
    total = r["csv"]["linhas"]
    at, pr = r["atual"], r["proposta"]

    def ad(k, antes, depois, s="", destaque=False):
        return (f'<div class="ad{" destaque" if destaque else ""}"><div class="k">{k}</div><div class="ad-v"><span class="antes">{antes}</span>'
                f'<span class="seta" aria-label="passa para">→</span><span class="depois">{depois}</span></div>'
                f'{f"<div class=s>{s}</div>" if s else ""}</div>')

    cart, pd_atual = numeros_carteira(r, det)
    ca, cp = cart["atual"], cart["proposta"]
    antes_depois = (
        ad("Dinheiro emprestado", curto(ca["valor"]), curto(cp["valor"]),
           f"{mi(cp['valor'] - ca['valor'])} · {num(at['aprovados'])} → {num(pr['aprovados'])} aprovados")
        + ad("Calote esperado", pct(ca["calote"]), pct(cp["calote"]),
             f"do dinheiro emprestado · cerca de {num(ca['contratos_calote'])} → {num(cp['contratos_calote'])} contratos")
        + ad("Perda com calote", curto(ca["perda"]), curto(cp["perda"]), f"{curto(ca['perda'] - cp['perda'])} a menos")
        + ad("Lucro esperado", mi(ca["lucro"]), mi(cp["lucro"]),
             f"<b>{mi(r['ganho_estimado'])}</b> sobre a atual · {pct(cp['lucro'] / cp['valor'])} sobre o emprestado", destaque=True))

    # para onde vão os pedidos
    segs = [("As duas aprovam o mesmo valor (ou maior)", "f-igual", "Igual: aprova"),
            ("As duas aprovam, a proposta reduz o valor", "f-reduz", "Aprova com valor menor"),
            ("A atual aprova, a proposta nega", "f-nega", "Passa a negar"),
            ("A atual nega, a proposta aprova", "f-aprova", "Passa a aprovar"),
            ("As duas negam", "f-negam", "Igual: nega")]
    barras, leg = [], []
    for g, cls, rot in segs:
        n = dec.get(g, {}).get("pedidos", 0)
        if not n:
            continue
        txt = num(n) if n / total >= 0.05 else ""
        barras.append(f'<span class="{cls}" style="flex:{n} 1 0" data-tip="{e(rot)}: {num(n)} pedidos">{txt}</span>')
        leg.append(f'<li><i class="{cls}"></i>{rot} <b>{num(n)}</b></li>')
    n_reduz = dec.get("As duas aprovam, a proposta reduz o valor", {}).get("pedidos", 0)

    # 1. passa a negar: motivo da proposta para cada pedido que a atual aprovava
    nega = det[(det["decisao_atual"] == "APROVADO") & (det["decisao"] == "NEGADO")]
    l_nega = []
    for motivo, qtd in nega["motivo"].value_counts().items():
        if nega.loc[nega["motivo"] == motivo, "passo"].iloc[0] == 5:
            pd_mod = float(nega.loc[nega["motivo"] == motivo, "pd"].mean())
            l_nega.append(_linha_mud("Risco alto pelo modelo, mesmo com valor menor", qtd, pd_mod, media,
                                     f"Chance de calote estimada pelo modelo: {pct(pd_mod, 0)} em média (média da carteira {pct(media, 0)})"))
            continue
        rot = re.sub(r"\s*\(.*\)$", "", motivo)
        chave = next((t for m, t in MOTIVO_PADRAO if m in motivo), None)
        l_nega.append(_linha_mud(rot[:1].upper() + rot[1:], qtd, _pd_padrao(pads, chave, "risco") if chave else None, media))

    # 2. passa a aprovar: por que a atual negava (score <= 600, renda <= R$ 2.000, restrição)
    aprova = det[(det["decisao_atual"] == "NEGADO") & (det["decisao"] == "APROVADO")]
    s, rd, x = aprova["score"] <= 600, aprova["renda_declarada"] <= 2000, aprova["restricoes_ativas"] >= 1
    k = s.astype(int) + rd.astype(int) + x.astype(int)
    rot_score = f"Score entre {num(P['score_min'])} e 600" if P["score_min"] is not None else "Score até 600"
    rot_renda = (f"Renda declarada entre {brl(P['renda_min'])} e R$ 2.000" if P["renda_min"] is not None
                 else "Renda declarada até R$ 2.000")
    l_aprova = [_linha_mud(rot_score, int((s & (k == 1)).sum()), _pd_padrao(pads, "Score 450", "oportunidade"), media),
                _linha_mud(rot_renda, int((rd & (k == 1)).sum()), _pd_padrao(pads, "Renda até", "oportunidade"), media),
                _linha_mud("1 restrição no nome", int((x & (k == 1)).sum()), _pd_padrao(pads, "restrição", "oportunidade"), media)]
    if (k >= 2).any():
        l_aprova.append(_linha_mud("Mais de um desses", int((k >= 2).sum()), None, media))
    restr = (f" {P['restricoes_max'] + 1:.0f} ou mais restrições continuam negadas: ninguém assim foi aprovado no histórico, "
             "então não dá para medir o risco." if P["restricoes_max"] is not None else "")

    # 3. empresta menos
    l_reduz = [_linha_mud("Cortados pela regra atual (30% da renda declarada)", None,
                          _pd_padrao(pads, "Reduzidos ao limite"), media),
               _linha_mud("Parcela acima de 50% da sobra da conta", None, _pd_padrao(pads, "acima de 50% da sobra"), media)]
    n_red_total = int(pr.get("reduzidos", 0))

    cartoes = (
        _cartao_mud("nega", "Passa a negar", "Quem a atual aprova, mas não paga", dec.get("A atual aprova, a proposta nega"),
                    "A atual olha score e renda declarada e não vê quem já está no limite. O extrato da conta mostra.", l_nega,
                    "Um calote apaga o lucro de 4 bons pagadores: perde 60% do valor, contra 15% de ganho de quem paga.")
        + _cartao_mud("aprova", "Passa a aprovar", "Bom pagador que a atual nega", dec.get("A atual nega, a proposta aprova"),
                      "Sem sinal de alerta no extrato, esses clientes pagam tão bem quanto a média, ou melhor.", l_aprova,
                      "Só aprova quem não tem sinal de alerta." + restr)
        + _cartao_mud("reduz", "Empresta menos", "Valor que cabe no bolso", dec.get("As duas aprovam, a proposta reduz o valor"),
                      f"A atual limita a parcela a {pct(P['teto_comprometimento'], 0)} da renda declarada. A proposta também a limita a "
                      f"{pct(P['teto_parcela_sobre_sobra'], 0)} do que sobra na conta (o que entra menos o que sai).", l_reduz,
                      f"Contando os que passam a ser aprovados, {num(n_red_total)} pedidos saem com valor menor que o pedido.", cab_qtd=""))

    v4 = ""
    if P["meses_cheque_max"] is None and P["consultas_90d_max"] is None and P["saidas_sobre_entradas_max"] == 0.80:
        v4 = ("""<p class="small mud-nota"><b>Depois das respostas da Fortuna (11/11):</b> cheque especial e consultas ao CPF deixaram de negar sozinhos.
    Quase todos esses clientes gastam mais de 80% do que entra, e essa regra continua negando. Efeito: 6 pedidos a mais aprovados.</p>""")

    return f"""
<section class="wrap" id="resumo">
  {bloco_pitch(r, det, cart)}
  <details class="det-resumo"><summary>Ver em detalhe: cenários, onde está o dinheiro, de onde vem o lucro e cada regra</summary>
  <h3>Antes e depois</h3>
  <div class="ad-grid">{antes_depois}</div>
  <p class="small muted">Nos {num(total)} pedidos de outubro de 2026, pela chance de calote que o modelo estima para cada pedido.
  Regras do desafio: +15% em dia, +5% com atraso, −60% no calote.</p>

  {bloco_cenarios(cart)}
  {bloco_faixas(cart)}
  {bloco_fontes(r, det, pd_atual)}

  <h3>Para onde vão os {num(total)} pedidos</h3>
  <p class="small"><b>{num(r['diferencas_vs_atual'])}</b> decisões mudam. Em outros <b>{num(n_reduz)}</b>, muda só o valor.</p>
  <div class="fluxo" role="img" aria-label="{e(', '.join(re.sub('<[^>]+>', '', x) for x in leg))}">{"".join(barras)}</div>
  <ul class="fluxo-leg">{"".join(leg)}</ul>

  <h3>Como funciona cada mudança</h3>
  <p class="small muted">Barras: calote que clientes iguais deram no histórico. O traço marca a média da carteira ({pct(media, 0)}).</p>
  {cartoes}
  {v4}
  {bloco_atencao(r, det, cart, pd_atual)}
  </details>
</section>"""


def bloco_simulador() -> tuple[str, str]:
    """Seção e scripts do simulador. Sem output/simulador.json, o painel sai sem o simulador."""
    caminho = SAIDA / "simulador.json"
    if not caminho.exists():
        return "", ""
    dados = caminho.read_text(encoding="utf-8").replace("</", "<\\/")
    motor = (RAIZ / "src" / "simulador.js").read_text(encoding="utf-8")
    tela = (RAIZ / "src" / "simulador_ui.js").read_text(encoding="utf-8")
    secao = """
<section class="wrap" id="simulador">
  <div class="parte">Parte 2 · experimentação</div>
  <h2>Simulador: teste a política antes de aprovar</h2>
  <p class="lead">Ligue, desligue ou mude o corte de cada regra. O painel refaz na hora as decisões dos 2.000 pedidos novos, com o mesmo
  modelo do pipeline, e mostra quanto calote clientes iguais tiveram no histórico. Com os cortes da proposta, ele reproduz o arquivo de decisões pedido a pedido.</p>
  <div class="tiles" id="sim-tiles"></div>
  <div class="callout aviso" id="sim-aviso" hidden></div>
  <div class="sim-grid">
    <div class="sim-grupo"><div class="sim-cab"><h3>Passo 2 · Faixas sem histórico</h3></div><div id="sim-p2"></div></div>
    <div class="sim-grupo"><div class="sim-cab"><h3>Passo 3 · Sinais de alerta</h3></div><div id="sim-p3"></div></div>
    <div class="sim-grupo"><div class="sim-cab"><h3>Passo 4 · Teto pela capacidade</h3><span class="sim-cnt" id="sim-p4-cnt"></span></div><div id="sim-p4"></div></div>
    <div class="sim-grupo"><div class="sim-cab"><h3>Passo 5 · Risco e retorno</h3><span class="sim-cnt" id="sim-p5-cnt"></span></div><div id="sim-p5"></div>
      <p class="small muted">O modelo escolhe o valor de maior resultado esperado até o teto. A margem é a folga exigida para aprovar.</p></div>
  </div>
  <div class="sim-acoes">
    <label class="small">Analista responsável <input id="sim-analista" placeholder="nome de quem aprova" autocomplete="name"></label>
    <button type="button" id="sim-aprovar">Aprovar esta versão</button>
    <button type="button" class="ex" id="sim-padrao">Voltar à proposta</button>
  </div>
  <div class="decide" id="sim-aprovado" hidden></div>
  <h3>Pedidos que mudam em relação à proposta</h3>
  <div id="sim-mudancas"></div>
</section>
"""
    scripts = (f'<script type="application/json" id="sim-dados">{dados}</script>\n'
               f"<script>\n{motor}\n</script>\n<script>\n{tela}\n</script>\n")
    return secao, scripts


def gerar(resumo_path: Path = SAIDA / "resumo.json", destino: Path = SAIDA / "painel.html"):
    r = json.loads(Path(resumo_path).read_text(encoding="utf-8"))
    av_path = SAIDA / "avaliacao.json"
    av = json.loads(av_path.read_text(encoding="utf-8")) if av_path.exists() else None
    det = pd.read_csv(SAIDA / "decisoes_detalhadas.csv")

    media = r["padroes_ref"]["pd_media"]
    riscos = [p for p in r["padroes"] if p["tipo"] == "risco"]
    oport = [p for p in r["padroes"] if p["tipo"] == "oportunidade"]
    neutros = [p for p in r["padroes"] if p["tipo"] == "neutro"]
    passos = pd.DataFrame(r["por_passo"])
    cont = passos.groupby("passo")["pedidos"].sum().to_dict()
    por_motivo = {row["motivo"]: row["pedidos"] for row in r["por_passo"]}
    P = r["parametros"]
    L = r["taxa_atraso"]
    b = r.get("bureau_api") or r["bureau"]

    # ---- onde a atual erra
    erra = tabela(["Grupo (histórico, desfecho real)", "Contratos", "Inadimplência (KM)", "Valor emprestado"],
                  [[e(g["grupo"]), num(g["n"]), pct(g["pd"]), brl(g["valor_total"])] for g in r["onde_atual_erra"]],
                  {1: "n", 2: "n", 3: "n"})

    # ---- varredura da IA
    varr = tabela(["Variável", "Corte encontrado", "Inadimplência no grupo de risco", "Contratos no grupo", "Do outro lado"],
                  [[e(v["rotulo"]), e(v["condicao"]), pct(v["pd_grupo_risco"]), num(v["n_grupo_risco"]), pct(v["pd_outro_lado"])]
                   for v in r["varredura"][:12]], {2: "n", 3: "n", 4: "n"})
    arv = "".join(f'<li><span class="pdv">{pct(a["pd"])}</span> <span class="nn">{num(a["n"])} contratos</span> {e(a["regra"])}</li>'
                  for a in r["arvore"])
    imp = pd.Series(r["modelo"]["importancia"])
    imp = (imp / imp.sum()).head(8)
    imp_html = "".join(
        f'<li><span class="lab">{e(ROTULOS_FEATURE.get(k, k))}</span><span class="ibar"><span style="width:{v / imp.max() * 100:.0f}%"></span></span><span class="n">{pct(v, 0)}</span></li>'
        for k, v in imp.items())

    # ---- decomposição
    ordem = ["A atual aprova, a proposta nega", "A atual nega, a proposta aprova",
             "As duas aprovam, a proposta reduz o valor", "As duas aprovam o mesmo valor (ou maior)", "As duas negam"]
    dec = {d["grupo"]: d for d in r["decomposicao"]}
    dec_linhas = []
    for g in ordem:
        if g in dec:
            d = dec[g]
            dec_linhas.append([e(g), num(d["pedidos"]), brl(d["valor_atual"]), brl(d["valor_proposta"]),
                               brl(d["ev_atual"]), brl(d["ev_proposta"]), f'<b>{mi(d["ganho"])}</b>'])
    dec_linhas.append(["<b>Total</b>", num(sum(d["pedidos"] for d in r["decomposicao"])), brl(r["atual"]["valor"]),
                       brl(r["proposta"]["valor"]), brl(r["atual"]["ev_modelo"]), brl(r["proposta"]["ev_modelo"]),
                       f'<b>{mi(r["ganho_estimado"])}</b>'])
    decomp = tabela(["Grupo", "Pedidos", "Valor (atual)", "Valor (proposta)", "Resultado esperado (atual)",
                     "Resultado esperado (proposta)", "Ganho"], dec_linhas, {i: "n" for i in range(1, 7)})

    # ---- validação
    if av:
        oot = av["fora_do_tempo"]["por_trimestre"]
        oot_svg = grafico_oot(oot)
        oot_tab = tabela(["Trimestre", "Contratos", "Calotes observados", "Calotes previstos", "No treino?"],
                         [[t["trimestre"], num(t["contratos"]), num(t["calotes_observados"]), num(t["calotes_previstos"], 1),
                           "sim" if t["no_treino"] else "não"] for t in oot], {1: "n", 2: "n", 3: "n"})
        bt = {x["cfg"]: x for x in av["backtest"]}
        bt_tab = tabela(["Política (10.000 pedidos históricos)", "Aprovados", "Valor aprovado", "Resultado esperado", "Ganho sobre a atual"],
                        [[e(k), num(bt[k]["aprovados"]), brl(bt[k]["valor"]), brl(bt[k]["resultado"]),
                          "—" if k == "atual" else mi(bt[k]["ganho_vs_atual"])]
                         for k in ["atual", "proposta", "margem 0%", "margem 3%", "teto 30% da sobra", "teto 50% da sobra"] if k in bt],
                        {1: "n", 2: "n", 3: "n", 4: "n"})
        validacao = f"""
      <h3>O modelo acerta quem não viu? Validação fora do tempo</h3>
      <p>Treinado só com pedidos até setembro de 2025, o modelo previu os calotes dos trimestres seguintes, incluindo todo o piloto,
      que ele nunca viu. Previsto e observado ficam próximos em todos os trimestres. AUC fora do tempo: <b>{num(av['fora_do_tempo']['auc'], 2)}</b>.</p>
      <div class="legend"><span><i class="sw s1"></i>Calotes observados até 30/09/2026</span><span><i class="sw s2"></i>Previstos pelo modelo</span></div>
      <div class="chartbox">{oot_svg}</div>
      <details><summary>Ver como tabela</summary>{oot_tab}</details>
      <h3>Backtest no histórico</h3>
      <p>Cada pedido histórico foi decidido por um modelo treinado sem ele (validação cruzada em 5 partes). O resultado esperado usa as regras do desafio.
      As variações mostram que o ganho não depende de um ajuste fino dos parâmetros.</p>
      {bt_tab}"""
    else:
        validacao = "<p>Rode <code>python avaliar_historico.py</code> para incluir a validação fora do tempo e o backtest.</p>"

    cal = r["modelo"]["calibracao"]
    cal_tab = tabela(["Faixa de risco", "Contratos", "PD prevista (fora da amostra)", "Inadimplência observada (KM)"],
                     [[str(int(c["faixa"]) + 1), num(c["n"]), pct(c["pd_calibrada"]), pct(c["pd_km"])] for c in cal],
                     {1: "n", 2: "n", 3: "n"})
    piso = min(c["pd_calibrada"] for c in cal)
    metade = sorted(cal, key=lambda c: c["pd_calibrada"])[: len(cal) // 2]
    pd_metade, km_metade = np.mean([c["pd_calibrada"] for c in metade]), np.mean([c["pd_km"] for c in metade])

    # ---- dados para a consulta de pedido
    cols = ["id_pedido", "valor_solicitado", "prazo_meses", "renda_declarada", "tipo_vinculo", "score", "restricoes_ativas",
            "consultas_90_dias", "parcelas_outras_instituicoes", "mov_entradas_med", "mov_saidas_med", "mov_meses_cheque",
            "mov_saidas_sobre_entradas", "renda_decl_sobre_real", "mov_entradas_cv", "decisao", "valor_aprovado", "passo",
            "motivo", "pd", "p_atraso", "ev_modelo", "valor_teto", "decisao_atual", "valor_atual", "ev_atual"]
    dj = det[cols].replace({np.nan: None})
    dados = json.dumps(dj.values.tolist(), ensure_ascii=False, separators=(",", ":"), default=float)
    exemplos = []
    for passo, rot in [(6, "aprovado"), (6, "reduzido"), (5, "risco"), (3, "alerta"), (2, "sem histórico")]:
        s = det[det["passo"] == passo]
        if rot == "reduzido":
            s = s[s["motivo"] == "aprovado com valor reduzido"]
        elif rot == "aprovado":
            s = s[s["motivo"] == "aprovado no valor pedido"]
        if len(s):
            exemplos.append((s.iloc[0]["id_pedido"], rot))
    ex_html = "".join(f'<button type="button" class="ex" data-id="{e(i)}">{e(i)} · {e(t)}</button>' for i, t in exemplos)
    primeiro = exemplos[0][0] if exemplos else det.iloc[0]["id_pedido"]

    sim_secao, sim_scripts = bloco_simulador()

    alvo = r["alvo"]
    restr2 = por_motivo.get("2+ restrições ativas (nunca aprovado no histórico)", 0)

    # charset primeiro: servido por http.server (Docker) sem charset no cabeçalho, o navegador cairia em Latin-1
    pagina = f"""<meta charset="utf-8">
<title>Painel de Risco Fortuna</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: relatório de uma coluna para o analista de risco. Resumo primeiro, depois padrões, política, prova e consulta. */
:root {{
  --bg: #f4f6f5; --surface: #ffffff; --fg: #13201d; --muted: #566661; --line: #dbe3e0; --accent: #0f6e5c;
  --s1: #2a78d6; --s2: #eb6834; --risk: #b42318; --good: #067647; --warn: #9a4a07; --band: #e9efed;
  --risk-bg: #fdeceb; --good-bg: #e6f4ec;
  --f-sans: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif; --f-mono: "IBM Plex Mono", ui-monospace, Consolas, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #0e1513; --surface: #151e1c; --fg: #e4ece9; --muted: #98a8a3; --line: #2a3734; --accent: #41c3a2;
  --s1: #3987e5; --s2: #d95926; --risk: #f97066; --good: #47cd89; --warn: #fdb022; --band: #1b2724;
  --risk-bg: #3a1a18; --good-bg: #13301f; color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --bg: #0e1513; --surface: #151e1c; --fg: #e4ece9; --muted: #98a8a3; --line: #2a3734; --accent: #41c3a2;
  --s1: #3987e5; --s2: #d95926; --risk: #f97066; --good: #47cd89; --warn: #fdb022; --band: #1b2724;
  --risk-bg: #3a1a18; --good-bg: #13301f; color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ background: var(--bg); color: var(--fg); font-family: var(--f-sans); font-size: 15px; line-height: 1.55; }}
.wrap {{ max-width: 1060px; margin: 0 auto; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }}
header.wrap {{ padding-block: 24px 4px; }}
.eyebrow {{ font-family: var(--f-mono); font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }}
h1 {{ font-size: clamp(26px, 4vw, 36px); line-height: 1.15; margin: 8px 0 10px; text-wrap: balance; font-weight: 700; }}
h2 {{ font-size: 24px; margin: 0 0 6px; text-wrap: balance; }}
h3 {{ font-size: 17px; margin: 28px 0 6px; }}
h4 {{ font-size: 15px; margin: 0; }}
p {{ max-width: 72ch; margin: 6px 0; }}
.lead {{ color: var(--muted); font-size: 16px; }}
nav.wrap {{ display: flex; flex-wrap: wrap; gap: 6px 14px; padding-block: 10px; font-size: 13px; }}
nav a {{ color: var(--accent); text-decoration: none; }} nav a:hover {{ text-decoration: underline; }}
section.wrap {{ padding-block: 28px; border-top: 1px solid var(--line); }}
.parte {{ font-family: var(--f-mono); font-size: 12px; color: var(--accent); letter-spacing: .06em; text-transform: uppercase; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-top: 16px; }}
.tile {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; min-width: 0; }}
.tile .k {{ font-size: 12px; color: var(--muted); }}
.tile .v {{ font-family: var(--f-mono); font-size: 24px; font-weight: 500; font-variant-numeric: tabular-nums; margin-top: 2px; }}
.tile .s {{ font-size: 12px; color: var(--muted); }}
.tile.destaque .v {{ color: var(--accent); }}
.callout {{ background: var(--band); border-radius: 8px; padding: 14px 16px; margin: 14px 0; }}
ul.pads {{ list-style: none; padding: 0; margin: 12px 0 0; display: grid; gap: 10px; }}
.pad {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; min-width: 0; }}
.pad-top {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
.chip {{ font-size: 11px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; border-radius: 4px; padding: 2px 6px; }}
.chip.risco {{ color: var(--risk); background: var(--risk-bg); }}
.chip.oportunidade {{ color: var(--good); background: var(--good-bg); }}
.chip.neutro {{ color: var(--muted); background: var(--band); }}
.frase {{ margin: 8px 0; }}
.bar {{ position: relative; height: 10px; background: var(--band); border-radius: 4px; max-width: 560px; }}
.bar .fill {{ position: absolute; inset: 0 auto 0 0; background: var(--s1); border-radius: 0 4px 4px 0; }}
.bar .media {{ position: absolute; top: -4px; bottom: -4px; width: 2px; background: var(--fg); }}
.meta {{ display: flex; flex-wrap: wrap; gap: 4px 18px; font-size: 13px; color: var(--muted); margin-top: 8px; max-width: none; }}
.meta b {{ color: var(--fg); font-variant-numeric: tabular-nums; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; color: var(--muted); margin: 8px 0; }}
.legend .sw {{ display: inline-block; width: 12px; height: 12px; border-radius: 3px; vertical-align: -2px; margin-right: 6px; }}
.sw.s1 {{ background: var(--s1); }} .sw.s2 {{ background: var(--s2); }} .sw.media {{ background: var(--fg); width: 2px; }}
.tbl {{ overflow-x: auto; margin: 10px 0; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }}
th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }}
th {{ font-size: 12px; color: var(--muted); font-weight: 600; white-space: nowrap; }}
tr:last-child td {{ border-bottom: 0; }}
td.n {{ text-align: right; font-family: var(--f-mono); font-variant-numeric: tabular-nums; white-space: nowrap; }}
ol.passos {{ list-style: none; padding: 0; margin: 14px 0; display: grid; gap: 10px; counter-reset: p; }}
ol.passos > li {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px 14px 56px; position: relative; counter-increment: p; min-width: 0; }}
ol.passos > li::before {{ content: counter(p); position: absolute; left: 16px; top: 13px; width: 26px; height: 26px; border-radius: 50%; background: var(--accent); color: var(--surface); font-family: var(--f-mono); font-weight: 500; display: grid; place-items: center; font-size: 13px; }}
ol.passos .cnt {{ font-family: var(--f-mono); font-size: 13px; color: var(--muted); }}
ol.passos ul {{ margin: 6px 0 0; padding-left: 18px; display: grid; gap: 2px; }}
code, .mono {{ font-family: var(--f-mono); font-size: .92em; }}
.formula {{ font-family: var(--f-mono); background: var(--band); border-radius: 6px; padding: 10px 12px; overflow-x: auto; font-size: 13px; }}
.chartbox {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 8px; overflow-x: auto; }}
svg.chart {{ width: 100%; min-width: 520px; height: auto; display: block; }}
svg .grid {{ stroke: var(--line); stroke-width: 1; }} svg .eixo {{ stroke: var(--muted); stroke-width: 1; }}
svg .tick, svg .lbl {{ fill: var(--muted); font-size: 11px; font-family: var(--f-mono); }}
svg .s1 {{ fill: var(--s1); }} svg .s2 {{ fill: var(--s2); }} svg .faixa {{ fill: var(--band); }}
svg .hit {{ fill: transparent; cursor: crosshair; }} svg .hit:hover {{ fill: var(--fg); fill-opacity: .05; }}
details {{ margin: 8px 0; }} summary {{ cursor: pointer; color: var(--accent); font-size: 13px; }}
ol.arv {{ padding-left: 0; list-style: none; display: grid; gap: 6px; font-size: 13.5px; }}
ol.arv .pdv {{ display: inline-block; min-width: 58px; font-family: var(--f-mono); font-weight: 500; }}
ol.arv .nn {{ display: inline-block; min-width: 110px; color: var(--muted); font-family: var(--f-mono); font-size: 12px; }}
ul.imp {{ list-style: none; padding: 0; display: grid; gap: 6px; max-width: 620px; }}
ul.imp li {{ display: grid; grid-template-columns: minmax(0, 1fr) 160px 44px; gap: 10px; align-items: center; font-size: 13.5px; }}
ul.imp .ibar {{ height: 8px; background: var(--band); border-radius: 4px; position: relative; }}
ul.imp .ibar span {{ position: absolute; inset: 0 auto 0 0; background: var(--s1); border-radius: 0 4px 4px 0; }}
ul.imp .n {{ font-family: var(--f-mono); text-align: right; font-size: 12px; color: var(--muted); }}
.decide {{ border-left: 3px solid var(--accent); padding: 8px 14px; background: var(--surface); border-radius: 0 8px 8px 0; margin: 14px 0; }}
.busca {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 12px 0; }}
.busca input {{ font: inherit; font-family: var(--f-mono); padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); color: var(--fg); width: 150px; }}
button {{ font: inherit; font-size: 13px; padding: 7px 12px; border-radius: 6px; border: 1px solid var(--accent); background: var(--accent); color: var(--surface); cursor: pointer; }}
button.ex {{ background: transparent; color: var(--accent); }}
button:focus-visible, input:focus-visible, a:focus-visible, summary:focus-visible {{ outline: 2px solid var(--s1); outline-offset: 2px; }}
.ficha {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 16px; display: grid; gap: 14px; }}
.ficha-top {{ display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: baseline; }}
.pill {{ font-weight: 700; font-size: 13px; padding: 3px 10px; border-radius: 999px; }}
.pill.APROVADO {{ background: var(--good-bg); color: var(--good); }} .pill.NEGADO {{ background: var(--risk-bg); color: var(--risk); }}
.ficha .grid2 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 6px 18px; font-size: 13.5px; }}
.ficha .grid2 div {{ display: flex; justify-content: space-between; gap: 10px; border-bottom: 1px dashed var(--line); padding: 3px 0; }}
.ficha .grid2 span:last-child {{ font-family: var(--f-mono); font-variant-numeric: tabular-nums; }}
ol.trilha {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; font-size: 13.5px; }}
ol.trilha li {{ display: grid; grid-template-columns: 22px minmax(0, 1fr); gap: 8px; }}
ol.trilha .st {{ font-weight: 700; text-align: center; }}
ol.trilha .ok {{ color: var(--good); }} ol.trilha .no {{ color: var(--risk); }} ol.trilha .na {{ color: var(--muted); }}
ol.trilha li.na {{ color: var(--muted); }}
#tip {{ position: fixed; pointer-events: none; z-index: 20; background: var(--fg); color: var(--bg); font-size: 12px; padding: 6px 8px; border-radius: 6px; max-width: 280px; }}
.muted {{ color: var(--muted); }} .small {{ font-size: 13px; }}
footer.wrap {{ padding-block: 24px 40px; color: var(--muted); font-size: 12.5px; border-top: 1px solid var(--line); }}
@media (prefers-reduced-motion: no-preference) {{ .bar .fill {{ transition: width .4s ease-out; }} }}
{SIM_CSS}{MUDA_CSS}{PITCH_CSS}</style>

<header class="wrap">
  <div class="eyebrow">Fortuna Crédito · Time Dividendos · Hackathon GOW 2026</div>
  <h1>Política de crédito proposta</h1>
  <p class="lead">Feita com IA a partir de {num(alvo['contratos_aprovados'])} contratos do histórico. A IA sugere; o analista de risco decide o que entra em produção.</p>
  <p class="small muted">Gerado pelo pipeline em {e(r['gerado_em'])} · dados do histórico com corte em 30/09/2026 · arquivo <span class="mono">{e(r['csv']['arquivo'])}</span></p>
</header>
<nav class="wrap" aria-label="Seções">
  <a href="#resumo">Resultado</a><a href="#padroes">1. Padrões encontrados</a><a href="#politica">2. Política proposta</a>{'<a href="#simulador">Simulador</a>' if sim_secao else ''}
  <a href="#ia">IA e analista</a><a href="#comparacao">Comparação com a atual</a><a href="#validacao">Validação</a><a href="#consulta">Consultar pedido</a><a href="#tecnico">Detalhes técnicos</a>
</nav>

{bloco_o_que_muda(r, det)}

<section class="wrap" id="padroes">
  <div class="parte">Parte 1</div>
  <h2>Padrões encontrados</h2>
  <div class="callout small">
    <b>Como medimos a inadimplência.</b> {num(alvo['contratos_aprovados'] - alvo['maduros'])} dos {num(alvo['contratos_aprovados'])} contratos aprovados ainda estavam em andamento na data de corte.
    Contar "em dia há 1 mês" como bom pagador daria <b>{pct(alvo['taxa_ingenua'])}</b> de inadimplência.
    Medindo só o tempo que cada contrato já foi observado (Kaplan-Meier), a inadimplência real da carteira é <b>{pct(alvo['taxa_km'])}</b>.
    Todas as taxas abaixo usam esse método. Calote = parcela vencida e não paga há mais de 60 dias: no histórico, ninguém que pagou atrasado passou de 60 dias.
  </div>
  <div class="legend"><span><i class="sw s1"></i>Inadimplência do grupo</span><span><i class="sw media"></i>Média da carteira ({pct(media)})</span></div>
  <h3>Sinais de risco</h3>
  <ul class="pads">{bloco_padroes(riscos, media)}</ul>
  <h3>Bons pagadores que a política atual nega</h3>
  <ul class="pads">{bloco_padroes(oport, media)}</ul>
  <h3>Parece risco, mas não é</h3>
  <ul class="pads">{bloco_padroes(neutros, media)}</ul>

  <h3>Onde a política atual erra, medido com desfecho real</h3>
  <p>Durante seis meses o piloto aprovou clientes que a política atual negaria. Isso permite medir os erros diretamente, sem depender do modelo.</p>
  {erra}

  <h3>Como a IA chegou a esses padrões</h3>
  <p><b>Varredura automática.</b> Para cada variável, uma árvore de decisão testou todos os cortes e escolheu o que mais separa quem pagou de quem não pagou.
  A árvore aponta a região. O corte final da política fica no ponto em que a taxa salta quando se olha faixa por faixa.
  Exemplo: com 7 consultas ao CPF, a inadimplência é de 26%; com 8, chega a 100%. Por isso o padrão marca 8 ou mais, e não 7 como sugeria a árvore.
  Outro caso: renda declarada entre 1,5x e 2x as entradas, sem outros alertas, dá só 7%. Por isso o corte é 2x.</p>
  {varr}
  <p><b>Combinações.</b> Uma árvore de 3 níveis sobre todas as variáveis encontrou estes grupos:</p>
  <ol class="arv">{arv}</ol>
  <p><b>O que mais pesa no modelo de risco</b> (participação no ganho de informação do modelo):</p>
  <ul class="imp">{imp_html}</ul>
{AGENTES_HTML}
</section>

<section class="wrap" id="politica">
  <div class="parte">Parte 2</div>
  <h2>Política proposta</h2>
  <p>Os passos rodam nesta ordem. O primeiro que nega encerra a análise. Ao lado de cada passo, quantos dos {num(r['csv']['linhas'])} pedidos novos ele decidiu.</p>
  <ol class="passos">
    <li><h4>Consulta o bureau</h4> <span class="cnt">{num(cont.get(1, 0))} negados</span>
      <p>Com repetição automática quando o bureau falha. Se nada voltar depois de todas as tentativas, nega e registra o caso para reanálise.</p></li>
    <li><h4>Nega o que o histórico não sabe avaliar</h4> <span class="cnt">{num(cont.get(2, 0))} negados</span>
      <ul>{itens_passo2(P, restr2)}</ul></li>
    <li><h4>Nega sinais de alerta</h4> <span class="cnt">{num(cont.get(3, 0))} negados</span>
      <ul>{itens_passo3(P)}</ul>
      {nota_passo3(P)}
      <p class="small muted">Com gasto acima de 80% das entradas ou renda declarada inflada, mais de 90% dos clientes deixaram de pagar. No pico de entradas, cerca de 27%, bem acima do limite (cerca de 16%) em que emprestar deixa de dar lucro. No pedido excessivo, cerca de 74%. Mesmo com a parcela entre 30% e 50% da sobra, fica perto de 50%, contra 11% a 19% de quem pede menos; na dívida acima de 35% das entradas, cerca de 32%.</p></li>
    <li><h4>Calcula o valor máximo que cabe no bolso</h4> <span class="cnt">{num(cont.get(4, 0))} negados</span>
      <ul><li>A parcela pode ser no máximo {pct(P['teto_parcela_sobre_sobra'], 0)} da sobra mensal (entradas menos saídas, média de 12 meses). Acima de 50%, quase todos deram calote.</li>
      <li>A parcela também fica em no máximo {pct(P['teto_parcela_sobre_entradas'], 0)} das entradas reais da conta. Vale a menor entre a média de 12 meses e a de 3 meses.</li>
      <li>E em no máximo {pct(P['teto_comprometimento'], 0)} da renda declarada, o mesmo limite da política atual.</li>
      <li>Se nem R$ 500 cabe, nega.</li></ul></li>
    <li><h4>Escolhe o valor pelo risco e pelo retorno</h4> <span class="cnt">{num(cont.get(5, 0))} negados</span>
      <p>O modelo estima a chance de calote para vários valores até o teto. A política escolhe o valor com o maior resultado esperado:</p>
      <div class="formula">resultado esperado = valor × [ (1 − PD) × (15% × (1 − A) + 5% × A) − 60% × PD ]</div>
      <p class="small">PD é a chance de calote para aquele valor. A é a chance de atrasar entre quem paga, medida no histórico: {pct(L['com_restricao'], 0)} com 1 restrição,
      {pct(L.get('divida_fora_alta', L['sem_restricao']), 0)} com dívidas em outros bancos acima de 30% da renda e {pct(L['sem_restricao'], 0)} nos demais.
      Fora desses grupos, o atraso é quase aleatório: um modelo com todas as variáveis acertou pouco (AUC 0,54).
      Se nem o menor valor rende pelo menos {pct(P['margem_min'], 0)} do valor emprestado, nega. Na prática, aprova com PD até cerca de 16%.</p></li>
    <li><h4>Aprova</h4> <span class="cnt">{num(cont.get(6, 0))} aprovados, {num(r['proposta']['reduzidos'])} com valor reduzido</span>
      <p>Aprova o valor escolhido. Quando é menor que o pedido, a parcela ficou grande demais para a renda real do cliente.</p></li>
  </ol>
  <div class="decide">
    <b>O analista decide.</b> Cada corte acima pode ser ligado, desligado ou mudado no <a href="#simulador">simulador</a>, logo abaixo,
    com o efeito nos 2.000 pedidos e o calote de clientes iguais no histórico. Só uma versão aprovada por ele vai para o pipeline.
    {f"Sugestão para decidir: um piloto pequeno e controlado com clientes de {P['restricoes_max'] + 1:.0f}+ restrições, hoje negados por falta de evidência, para medir o risco deles." if P['restricoes_max'] is not None else ""}
  </div>
</section>

{sim_secao}
<section class="wrap" id="ia">
  <h2>Onde a IA entra e onde o analista decide</h2>
  <div class="tiles">
    <div class="tile"><div class="k">IA · descoberta</div><p class="small">Árvores de decisão varrem todas as variáveis e combinações do histórico e encontram os cortes da Parte 1.
      Em paralelo, 7 pares de agentes de IA propõem padrões e tentam derrubá-los. As taxas de cada grupo são medidas sem contar contrato em andamento como bom pagador.</p></div>
    <div class="tile"><div class="k">IA · decisão</div><p class="small">No passo 5, 5 modelos de sobrevivência treinados no histórico estimam a chance de calote de cada pedido para cada valor possível.
      A política aprova o valor com o maior resultado esperado.</p></div>
    <div class="tile"><div class="k">Analista · aprovação</div><p class="small">No simulador, o analista liga, desliga e ajusta cada regra, vê o efeito e a evidência do histórico,
      e aprova a versão com o nome dele. Nenhuma política vai para produção sem essa aprovação.</p></div>
  </div>
  <h3>Como o analista valida uma mudança</h3>
  <ol class="small">
    <li><b>Testa no <a href="#simulador">simulador</a>.</b> Liga, desliga ou muda o corte de uma regra, sem ler código.
      O painel mostra na hora quantos pedidos mudam, o ganho pelo modelo e o calote de clientes iguais no histórico.</li>
    <li><b>Confere quando o modelo e o histórico discordam.</b> O painel avisa. Exemplo: desligar o pedido excessivo rende mais pelo modelo,
      mas bem menos se esses clientes repetirem o calote do histórico. Pedidos sem nenhum caso parecido no histórico também são sinalizados.</li>
    <li><b>Olha os pedidos que mudam</b>, um a um, na tabela do simulador ou em <a href="#consulta">Consultar pedido</a>.</li>
    <li><b>Aprova a versão com o nome dele.</b> O painel baixa <span class="mono">parametros_aprovados.json</span>, com os cortes e quem aprovou.</li>
    <li><b>O pipeline aplica só a versão aprovada:</b> <span class="mono">python gerar_decisoes.py --parametros parametros_aprovados.json</span>
      refaz o arquivo de decisões, valida o formato e refaz este painel.</li>
  </ol>
</section>

<section class="wrap" id="comparacao">
  <h2>Comparação com a política atual nos {num(r['csv']['linhas'])} pedidos novos</h2>
  <p>A política atual foi reproduzida exatamente: score acima de 600, renda acima de R$ 2.000 e nenhuma restrição.
  Quando a parcela passa de 30% da renda declarada, ela reduz o valor em vez de negar.
  A réplica acerta 100% das 8.737 decisões que a política atual tomou no histórico, e o valor aprovado bate até os centavos
  (teste automático em <span class="mono">tests/test_politica.py</span>).
  O resultado esperado usa o modelo calibrado e as regras do desafio: +15% em dia, +5% com atraso, −60% sem pagamento.</p>
  {decomp}
</section>

<section class="wrap" id="validacao">
  <h2>Validação</h2>
  {validacao}
  <h3>Calibração: a chance prevista bate com a observada?</h3>
  <p>A decisão usa a média de 5 modelos treinados com sementes diferentes, para que nenhuma decisão dependa do acaso.
  Cada modelo é calibrado fora da amostra: a chance prevista é ajustada para bater com a inadimplência observada (Kaplan-Meier) em 20 faixas.
  Na metade mais segura da carteira, o modelo não consegue separar os clientes: prevê {pct(pd_metade)} e a observada é {pct(km_metade)}.
  Por isso todos ali recebem praticamente a mesma chance, a partir de {pct(piso)}, e o valor deles não é reduzido por ruído.</p>
  <details><summary>Ver tabela de calibração</summary>{cal_tab}</details>
</section>

<section class="wrap" id="consulta">
  <h2>Consultar pedido</h2>
  <p>Mostra a decisão de qualquer pedido novo e por que ela foi tomada.</p>
  <form class="busca" id="f-busca" autocomplete="off">
    <label for="pedido" class="small">Pedido</label>
    <input id="pedido" name="pedido" value="{e(primeiro)}" placeholder="P-00070" spellcheck="false">
    <button type="submit">Ver decisão</button>
    <span class="small muted">Exemplos:</span> {ex_html}
  </form>
  <div id="ficha" class="ficha" aria-live="polite"></div>
</section>

<section class="wrap" id="tecnico">
  <h2>Detalhes técnicos</h2>
  <h3>Bureau de crédito</h3>
  <p>A API devolve 503 e responde devagar de propósito. O cliente faz timeout por chamada, repete com espera crescente em 503, timeout e erro de conexão,
  e consulta em paralelo. Respostas válidas ficam em cache local, porque a resposta de um cliente não muda.
  Números da última execução que chamou a API ({e(b.get('registrado_em', r['gerado_em']))}):</p>
  {tabela(["Medida", "Valor"], [[k, e(v)] for k, v in [
        ("Clientes consultados", num(b.get('clientes', 0))), ("Com dados", num(b.get('com_dados', 0))),
        ("Chamadas HTTP", num(b.get('chamadas_http', 0)) if b.get('chamadas_http') is not None else '—'),
        ("Respostas 503 tratadas", num(b.get('respostas_503', 0)) if b.get('respostas_503') is not None else '—'),
        ("Timeouts tratados", num(b.get('timeouts', 0)) if b.get('timeouts') is not None else '—'),
        ("Tentativas por cliente (média / máxima)", f"{b.get('tentativas_media', '—')} / {b.get('tentativas_max', '—')}"),
        ("Latência p50 / p95 / máxima", f"{b.get('latencia_p50_s', '—')} s / {b.get('latencia_p95_s', '—')} s / {round(b['latencia_max_s'], 1) if b.get('latencia_max_s') else '—'} s"),
        ("Duração da consulta", f"{b.get('duracao_s', '—')} s"), ("Sem dados após todas as tentativas", num(b.get('sem_dados', 0)))]], {1: "n"})}
  <h3>Modelo</h3>
  <p>Modelo de sobrevivência em tempo discreto: uma linha por parcela já observável, até o calote. Foram {num(r['modelo']['linhas_treino'])} linhas e {num(r['modelo']['eventos'])} calotes.
  O modelo estima a chance de o calote começar em cada parcela. A chance no contrato inteiro é 1 − ∏(1 − h).
  É um LightGBM raso com restrição de monotonicidade: o risco só pode subir quando a parcela sobe em relação à renda.
  A decisão usa a média de 5 modelos com sementes diferentes; com um modelo só, de 10 a 60 decisões mudavam entre sementes.
  Quando dois valores dão resultado esperado a até {pct(P['tolerancia_ev'], 0)} um do outro, a política fica com o maior.
  Gênero, CEP, estado civil e idade ficam fora da decisão.</p>
</section>

<footer class="wrap">Time Dividendos · Hackathon GOW 2026 · Painel gerado por <span class="mono">gerar_painel.py</span>. Os números vêm de <span class="mono">output/resumo.json</span> e <span class="mono">output/avaliacao.json</span>.</footer>
<div id="tip" hidden></div>

<script>
const COLS = {json.dumps(cols)};
const ROWS = {dados};
const IDX = new Map(ROWS.map((r, i) => [r[0], i]));
const PASSOS = ["Consulta o bureau", "Faixas com histórico", "Sinais de alerta", "Capacidade de pagamento", "Risco e retorno", "Aprovação"];
const fmtN = (v, c = 0) => v == null ? "—" : Number(v).toLocaleString("pt-BR", {{ minimumFractionDigits: c, maximumFractionDigits: c }});
const brl = (v, c = 2) => v == null ? "—" : "R$ " + fmtN(v, c);
const pct = (v, c = 1) => v == null ? "—" : fmtN(v * 100, c) + "%";
const esc = s => String(s ?? "").replace(/[&<>"]/g, ch => ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }})[ch]);
function mostrar(id) {{
  const el = document.getElementById("ficha");
  const i = IDX.get(id.trim().toUpperCase());
  if (i === undefined) {{ el.innerHTML = `<p>Pedido <b>${{esc(id)}}</b> não encontrado. Use um id dos novos pedidos, no formato P-00070.</p>`; return; }}
  const r = Object.fromEntries(COLS.map((c, k) => [c, ROWS[i][k]]));
  const sobra = r.mov_entradas_med - r.mov_saidas_med;
  const trilha = PASSOS.map((nome, k) => {{
    const n = k + 1;
    let st = "ok", s = "✓", txt = nome;
    if (n === r.passo && r.decisao === "NEGADO") {{ st = "no"; s = "✕"; txt += ": " + r.motivo; }}
    else if (n > r.passo) {{ st = "na"; s = "·"; txt += " (não avaliado)"; }}
    else if (n === 6) {{ txt += ": " + r.motivo; }}
    return `<li class="${{st}}"><span class="st ${{st}}">${{s}}</span><span>${{esc(txt)}}</span></li>`;
  }}).join("");
  const kv = (k, v) => `<div><span>${{k}}</span><span>${{v}}</span></div>`;
  el.innerHTML = `
    <div class="ficha-top"><b class="mono">${{esc(r.id_pedido)}}</b>
      <span class="pill ${{r.decisao}}">${{r.decisao === "APROVADO" ? "✓ APROVADO" : "✕ NEGADO"}}</span>
      <span>Aprovado: <b class="mono">${{brl(r.valor_aprovado)}}</b> de ${{brl(r.valor_solicitado)}} pedidos em ${{r.prazo_meses}} meses</span>
      <span class="muted small">Política atual: ${{r.decisao_atual}} ${{r.decisao_atual === "APROVADO" ? brl(r.valor_atual) : ""}}</span></div>
    <ol class="trilha">${{trilha}}</ol>
    <div class="grid2">
      ${{kv("Score", fmtN(r.score))}}${{kv("Restrições ativas", fmtN(r.restricoes_ativas))}}${{kv("Consultas ao CPF (90 dias)", fmtN(r.consultas_90_dias))}}
      ${{kv("Renda declarada", brl(r.renda_declarada, 0))}}${{kv("Entradas médias na conta", brl(r.mov_entradas_med, 0))}}${{kv("Sobra mensal", brl(sobra, 0))}}
      ${{kv("Saídas ÷ entradas", pct(r.mov_saidas_sobre_entradas, 0))}}${{kv("Renda declarada ÷ entradas", fmtN(r.renda_decl_sobre_real, 2) + "x")}}${{kv("Meses no cheque especial", fmtN(r.mov_meses_cheque))}}
      ${{kv("Dívidas em outros bancos", brl(r.parcelas_outras_instituicoes, 0))}}${{kv("Vínculo", esc(r.tipo_vinculo))}}${{kv("Teto pela capacidade", brl(r.valor_teto, 0))}}
      ${{kv("Chance de calote (valor escolhido)", pct(r.pd))}}${{kv("Chance de atraso", pct(r.p_atraso, 0))}}${{kv("Resultado esperado", brl(r.ev_modelo, 0))}}
    </div>`;
}}
document.getElementById("f-busca").addEventListener("submit", ev => {{ ev.preventDefault(); mostrar(document.getElementById("pedido").value); }});
document.querySelectorAll("#consulta button.ex[data-id]").forEach(b => b.addEventListener("click", () => {{ document.getElementById("pedido").value = b.dataset.id; mostrar(b.dataset.id); }}));
mostrar(document.getElementById("pedido").value);
const tip = document.getElementById("tip");
document.addEventListener("pointermove", ev => {{
  const t = ev.target.closest && ev.target.closest("[data-tip]");
  if (!t) {{ tip.hidden = true; return; }}
  tip.textContent = t.getAttribute("data-tip"); tip.hidden = false;
  const x = Math.min(ev.clientX + 12, window.innerWidth - tip.offsetWidth - 8);
  tip.style.left = x + "px"; tip.style.top = (ev.clientY + 14) + "px";
}});
</script>
{sim_scripts}{'<script>' + SEM_REGRA_JS + '</script>' if sim_scripts else ''}"""
    Path(destino).write_text(pagina, encoding="utf-8")
    return destino


if __name__ == "__main__":
    print(gerar())
