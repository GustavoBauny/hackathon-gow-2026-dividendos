"""Gera output/painel.html a partir de output/resumo.json, output/avaliacao.json e output/decisoes_detalhadas.csv.

Uso: python gerar_painel.py   (o gerar_decisoes.py já chama no final)
"""
from __future__ import annotations

import html
import json
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

    alvo = r["alvo"]
    restr2 = por_motivo.get("2+ restrições ativas (nunca aprovado no histórico)", 0)

    pagina = f"""<title>Painel de Risco Fortuna</title>
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
header.wrap {{ padding-block: 36px 8px; }}
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
</style>

<header class="wrap">
  <div class="eyebrow">Fortuna Crédito · Time Dividendos · Hackathon GOW 2026</div>
  <h1>Política de crédito proposta</h1>
  <p class="lead">O que a IA encontrou em {num(alvo['contratos_aprovados'])} contratos do histórico, como a nova política decide e o que ela faz com os {num(r['csv']['linhas'])} pedidos de outubro de 2026.
  A IA sugere; o analista de risco decide o que entra em produção.</p>
  <p class="small muted">Gerado pelo pipeline em {e(r['gerado_em'])} · dados do histórico com corte em 30/09/2026 · arquivo <span class="mono">{e(r['csv']['arquivo'])}</span></p>
</header>
<nav class="wrap" aria-label="Seções">
  <a href="#resumo">Resumo</a><a href="#padroes">1. Padrões encontrados</a><a href="#politica">2. Política proposta</a>
  <a href="#ia">IA e analista</a><a href="#comparacao">Comparação com a atual</a><a href="#validacao">Validação</a><a href="#consulta">Consultar pedido</a><a href="#tecnico">Detalhes técnicos</a>
</nav>

<section class="wrap" id="resumo">
  <h2>Resumo</h2>
  <div class="tiles">
    <div class="tile"><div class="k">Pedidos novos</div><div class="v">{num(r['csv']['linhas'])}</div><div class="s">outubro de 2026</div></div>
    <div class="tile"><div class="k">Aprovados</div><div class="v">{num(r['proposta']['aprovados'])}</div><div class="s">política atual: {num(r['atual']['aprovados'])}</div></div>
    <div class="tile"><div class="k">Valor aprovado</div><div class="v">{brl(r['proposta']['valor'] / 1e6, 1)} mi</div><div class="s">política atual: {brl(r['atual']['valor'] / 1e6, 1)} mi</div></div>
    <div class="tile"><div class="k">Decisões diferentes da atual</div><div class="v">{num(r['diferencas_vs_atual'])}</div><div class="s">{num(r['proposta']['reduzidos'])} aprovados com valor reduzido</div></div>
    <div class="tile destaque"><div class="k">Ganho estimado sobre a atual</div><div class="v">{mi(r['ganho_estimado'])}</div><div class="s">resultado esperado pelo modelo</div></div>
  </div>
</section>

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
  Exemplo: com 7 consultas ao CPF, a inadimplência é de 26%; com 8, chega a 100%. Por isso o corte é 8, e não o 7 da árvore.
  Outro caso: renda declarada entre 1,5x e 2x as entradas, sem outros alertas, dá só 7%. Por isso o corte é 2x.</p>
  {varr}
  <p><b>Combinações.</b> Uma árvore de 3 níveis sobre todas as variáveis encontrou estes grupos:</p>
  <ol class="arv">{arv}</ol>
  <p><b>O que mais pesa no modelo de risco</b> (participação no ganho de informação do modelo):</p>
  <ul class="imp">{imp_html}</ul>
</section>

<section class="wrap" id="politica">
  <div class="parte">Parte 2</div>
  <h2>Política proposta</h2>
  <p>Os passos rodam nesta ordem. O primeiro que nega encerra a análise. Ao lado de cada passo, quantos dos {num(r['csv']['linhas'])} pedidos novos ele decidiu.</p>
  <ol class="passos">
    <li><h4>Consulta o bureau</h4> <span class="cnt">{num(cont.get(1, 0))} negados</span>
      <p>Com repetição automática quando o bureau falha. Se nada voltar depois de todas as tentativas, nega e registra o caso para reanálise.</p></li>
    <li><h4>Nega o que o histórico não sabe avaliar</h4> <span class="cnt">{num(cont.get(2, 0))} negados</span>
      <ul><li>{P['restricoes_max'] + 1} ou mais restrições ativas ({num(restr2)} pedidos). Ninguém assim foi aprovado no histórico, então não há como medir o risco.</li>
      <li>Score abaixo de {num(P['score_min'])} ou renda abaixo de {brl(P['renda_min'])}, abaixo de qualquer cliente já aprovado.</li></ul></li>
    <li><h4>Nega sinais de alerta</h4> <span class="cnt">{num(cont.get(3, 0))} negados</span>
      <ul><li>Cheque especial em {P['meses_cheque_max'] + 1} ou mais meses no último ano.</li>
      <li>Saídas acima de {pct(P['saidas_sobre_entradas_max'], 0)} das entradas da conta.</li>
      <li>{P['consultas_90d_max'] + 1} ou mais consultas ao CPF em 90 dias.</li>
      <li>Renda declarada mais que {num(P['renda_decl_sobre_real_max'])} vezes as entradas reais.</li>
      <li>Pico de entradas: os 3 meses antes do pedido vêm {num((P['tendencia_entradas_max'] - 1) * 100)}% ou mais acima da média dos meses anteriores.</li>
      <li>Pedido maior que {num(P['pedido_sobre_entradas_max'])} vezes o que entra por mês na conta. Nega em vez de reduzir: no histórico, reduzir o valor não tirou o risco.</li>
      <li>Parcelas em outros bancos acima de {pct(P['outras_sobre_entradas_max'], 0)} do que entra na conta.</li></ul>
      <p class="small muted">Nos quatro primeiros grupos, de 82% a 100% dos clientes deixaram de pagar. No pico de entradas, cerca de 27%, bem acima do limite (cerca de 16%) em que emprestar deixa de dar lucro. No pedido excessivo, cerca de 74%, e 70% entre os que a política atual aprovou com o valor reduzido; na dívida acima de 35% das entradas, cerca de 32%.</p></li>
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
    <b>O analista decide.</b> Todo corte acima é um parâmetro em <span class="mono">src/politica.py</span> (classe <span class="mono">Parametros</span>).
    Mudar um valor e rodar <span class="mono">python gerar_decisoes.py</span> refaz as decisões e este painel em cerca de 2 minutos.
    Sugestão para decidir: um piloto pequeno e controlado com clientes de {P['restricoes_max'] + 1}+ restrições, hoje negados por falta de evidência, para medir o risco deles.
  </div>
</section>

<section class="wrap" id="ia">
  <h2>Onde a IA entra e onde o analista decide</h2>
  <div class="tiles">
    <div class="tile"><div class="k">IA · descoberta</div><p class="small">Árvores de decisão varrem todas as variáveis e combinações do histórico.
      Elas encontram os cortes e grupos da Parte 1. As taxas de cada grupo são medidas sem contar contrato em andamento como bom pagador.</p></div>
    <div class="tile"><div class="k">IA · decisão</div><p class="small">No passo 5, 5 modelos de sobrevivência treinados no histórico estimam a chance de calote de cada pedido para cada valor possível.
      A política aprova o valor com o maior resultado esperado.</p></div>
    <div class="tile"><div class="k">Analista · aprovação</div><p class="small">Os cortes dos passos 2 a 5 são parâmetros visíveis. O analista ajusta, roda de novo e compara.
      Nenhuma política vai para produção sem a aprovação dele.</p></div>
  </div>
  <h3>Como o analista valida uma mudança</h3>
  <ol class="small">
    <li>Muda um parâmetro em <span class="mono">src/politica.py</span>. Exemplo: aceitar 2 restrições, ou trocar o teto de 40% da sobra.</li>
    <li>Roda <span class="mono">python gerar_decisoes.py</span>, que refaz o arquivo e este painel, e <span class="mono">python avaliar_historico.py</span>, que refaz o backtest.</li>
    <li>Compara o ganho no backtest e roda os testes com <span class="mono">python -m unittest discover tests</span>.</li>
    <li>Confere os pedidos que mudaram em <span class="mono">output/decisoes_detalhadas.csv</span> ou com <span class="mono">python explicar.py P-xxxxx</span>.</li>
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
document.querySelectorAll("button.ex").forEach(b => b.addEventListener("click", () => {{ document.getElementById("pedido").value = b.dataset.id; mostrar(b.dataset.id); }}));
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
"""
    Path(destino).write_text(pagina, encoding="utf-8")
    return destino


if __name__ == "__main__":
    print(gerar())
