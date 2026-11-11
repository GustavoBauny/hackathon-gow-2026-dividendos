"""Descoberta de padrões no histórico, em linguagem de analista de risco.

1. Varredura automática: para cada variável, uma árvore de decisão de 1 nível encontra o corte que mais
   separa quem deu calote de quem pagou (em contratos com pelo menos metade da janela de risco observada).
2. Combinações: uma árvore de 3 níveis sobre todas as variáveis acha os grupos de maior e menor risco.
3. Para cada grupo, a taxa de calote é estimada por Kaplan-Meier (não subestima contratos recentes).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

from modelo import km_relativo, feats_valor

# variável -> (rótulo para o analista, formato do corte)
VARIAVEIS = {
    "parcela_sobre_sobra": ("parcela ÷ sobra mensal (entradas − saídas)", "pct"),
    "comprometimento": ("parcela ÷ renda declarada", "pct"),
    "comprometimento_real": ("parcela ÷ entradas reais na conta", "pct"),
    "comprometimento_total": ("(parcela + dívidas em outros bancos) ÷ renda declarada", "pct"),
    "mov_meses_cheque": ("meses com uso de cheque especial (últimos 12)", "int"),
    "mov_dias_cheque_total": ("dias no cheque especial (últimos 12 meses)", "int"),
    "mov_saidas_sobre_entradas": ("saídas ÷ entradas da conta", "pct"),
    "consultas_90_dias": ("consultas ao CPF em 90 dias", "int"),
    "renda_decl_sobre_real": ("renda declarada ÷ entradas reais", "x"),
    "mov_entradas_cv": ("instabilidade das entradas (coef. de variação)", "pct"),
    "mov_saldo_medio_med": ("saldo médio na conta", "brl"),
    "score": ("score do bureau", "int"),
    "renda_declarada": ("renda declarada", "brl"),
    "restricoes_ativas": ("restrições ativas no bureau", "int"),
    "meses_historico_bureau": ("meses de histórico no bureau", "int"),
    "divida_outras_sobre_renda": ("dívidas em outros bancos ÷ renda declarada", "pct"),
    "meses_conta": ("meses de conta na Fortuna", "int"),
    "idade": ("idade", "int"),
    "valor_aprovado": ("valor do empréstimo", "brl"),
    "prazo_meses": ("prazo em meses", "int"),
    "mov_tendencia_entradas": ("entradas dos últimos 3 meses ÷ meses anteriores", "x"),
}


def fmt(v, kind):
    if kind == "int":
        return f"{v:.0f}"
    if kind == "pct":
        return f"{v * 100:.0f}%"
    if kind == "brl":
        return f"R$ {v:,.0f}".replace(",", ".")
    if kind == "x":
        return f"{v:.2f}x".replace(".", ",")
    return f"{v:.0f}"


def preparar(hist_aprov: pd.DataFrame) -> pd.DataFrame:
    h = hist_aprov.reset_index(drop=True)
    h = h.drop(columns=[c for c in ["valor", "parcela", "comprometimento", "comprometimento_total",
                                    "comprometimento_real", "parcela_sobre_saldo", "parcela_sobre_sobra"] if c in h], errors="ignore")
    return pd.concat([h, feats_valor(h, h["valor_aprovado"])], axis=1)


def taxa(df: pd.DataFrame) -> tuple[float, int]:
    pd_, n = km_relativo(df)
    return (float(pd_) if n else float("nan")), int(n)


def varredura_univariada(h: pd.DataFrame, min_folha: int = 40) -> pd.DataFrame:
    base_pd, _ = taxa(h)
    treino = h[h["exposicao"] >= 0.5]
    linhas = []
    for col, (rotulo, kind) in VARIAVEIS.items():
        x = treino[[col]].astype(float)
        ok = x[col].notna()
        if ok.sum() < 200:
            continue
        t = DecisionTreeClassifier(max_depth=1, min_samples_leaf=min_folha).fit(x[ok], treino.loc[ok, "calote_obs"])
        if t.tree_.node_count < 3:
            continue
        corte = float(t.tree_.threshold[0])
        acima = h[h[col] > corte]
        abaixo = h[h[col] <= corte]
        pa, na = taxa(acima)
        pb, nb = taxa(abaixo)
        risco_acima = pa >= pb
        grupo, pd_g, n_g, outro = (acima, pa, na, pb) if risco_acima else (abaixo, pb, nb, pa)
        if kind == "int":  # corte de árvore em inteiro cai no meio (ex.: 1,5): mostra como >= 2 / <= 1
            txt = f"≥ {int(np.floor(corte)) + 1}" if risco_acima else f"≤ {int(np.floor(corte))}"
        else:
            txt = f"> {fmt(corte, kind)}" if risco_acima else f"≤ {fmt(corte, kind)}"
        linhas.append({
            "variavel": col, "rotulo": rotulo, "corte": corte, "corte_fmt": fmt(corte, kind), "condicao": txt,
            "lado_risco": ">" if risco_acima else "<=", "pd_grupo_risco": pd_g, "n_grupo_risco": n_g,
            "pd_outro_lado": outro, "lift": pd_g / base_pd if base_pd else np.nan,
            "separacao": abs(pa - pb),
        })
    return pd.DataFrame(linhas).sort_values("separacao", ascending=False).reset_index(drop=True)


def arvore_combinacoes(h: pd.DataFrame, profundidade: int = 3, min_folha: int = 60) -> pd.DataFrame:
    cols = [c for c in VARIAVEIS if c not in ("valor_aprovado", "idade", "meses_conta")]
    treino = h[h["exposicao"] >= 0.5]
    X = treino[cols].astype(float).fillna(-1)
    t = DecisionTreeClassifier(max_depth=profundidade, min_samples_leaf=min_folha, random_state=0).fit(X, treino["calote_obs"])
    folha_h = t.apply(h[cols].astype(float).fillna(-1))
    tree = t.tree_

    # reconstrói o caminho de cada folha
    caminhos = {}

    def anda(no, cond):
        if tree.children_left[no] == -1:
            caminhos[no] = cond
            return
        c = cols[tree.feature[no]]
        thr = tree.threshold[no]
        rot, kind = VARIAVEIS[c]
        if kind == "int":
            anda(tree.children_left[no], cond + [f"{rot} ≤ {int(np.floor(thr))}"])
            anda(tree.children_right[no], cond + [f"{rot} ≥ {int(np.floor(thr)) + 1}"])
        else:
            anda(tree.children_left[no], cond + [f"{rot} ≤ {fmt(thr, kind)}"])
            anda(tree.children_right[no], cond + [f"{rot} > {fmt(thr, kind)}"])

    anda(0, [])
    linhas = []
    for folha, cond in caminhos.items():
        g = h[folha_h == folha]
        pd_, n = taxa(g)
        linhas.append({"regra": " E ".join(cond), "pd": pd_, "n": n})
    return pd.DataFrame(linhas).sort_values("pd", ascending=False).reset_index(drop=True)


def _alerta(df: pd.DataFrame, incluir_pico: bool = True) -> pd.Series:
    entradas = df["mov_entradas_med"].where(df["mov_entradas_med"] > 0)
    a = ((df["mov_meses_cheque"] >= 2) | (df["mov_saidas_sobre_entradas"] > 0.8) |
         (df["consultas_90_dias"] >= 8) | (df["renda_decl_sobre_real"] > 2) |
         (df["valor_solicitado"] / entradas > 6).fillna(False) |                     # v3: pedido excessivo
         (df["parcelas_outras_instituicoes"] / entradas > 0.35).fillna(False))       # v3: dívida sobre as entradas
    return a | (df["mov_tendencia_entradas"] > 1.35) if incluir_pico else a


def _reduzido_pela_atual(h: pd.DataFrame) -> pd.Series:
    if h["politica_aplicada"].notna().any():   # histórico: o que de fato aconteceu
        return (h["politica_aplicada"] == "atual") & (h["valor_aprovado"] < h["valor_solicitado"])
    elegivel = (h["score"] > 600) & (h["renda_declarada"] > 2000) & (h["restricoes_ativas"] == 0)
    return elegivel & (h["parcela_solicitada"] > 0.30 * h["renda_declarada"])   # novos: o que a atual faria


# (tipo, título curto, sujeito da frase "Clientes ...", máscara, leitura para o analista)
SPECS = [
    ("risco", "Parcela acima de 50% da sobra mensal", "com parcela acima de 50% da sobra mensal (entradas menos saídas da conta)",
     lambda h, a: h["parcela_sobre_sobra"] > 0.5,
     "O corte mais forte da base: quase todos deixam de pagar, seja qual for o tamanho do pedido. Para quem pede um valor "
     "proporcional à conta, reduzir o valor resolve. Quem pede mais de 6x o que entra é negado (ver pedido excessivo)."),
    ("risco", "Parcela entre 40% e 50% da sobra", "com parcela entre 40% e 50% da sobra mensal",
     lambda h, a: (h["parcela_sobre_sobra"] > 0.4) & (h["parcela_sobre_sobra"] <= 0.5),
     "Zona de risco crescente antes do corte de 50%. A política proposta limita a parcela a 40% da sobra."),
    ("risco", "Reduzidos ao limite de 30% da renda declarada", "cujo pedido a política atual reduziu para a parcela caber em 30% da renda declarada",
     lambda h, a: _reduzido_pela_atual(h),
     "Cortar até exatamente 30% da renda declarada não basta. Três em cada quatro desse grupo pediram mais de 6 vezes o que entra "
     "na conta: é principalmente o pedido excessivo que explica o calote, e reduzir o valor não tirou esse risco."),
    ("risco", "Cheque especial recorrente", "que usaram cheque especial em 2 ou mais meses no último ano",
     lambda h, a: h["mov_meses_cheque"] >= 2,
     "Uso recorrente indica aperto financeiro crônico. Um mês isolado não muda o risco."),
    ("risco", "Gasto acima de 80% das entradas", "que gastam mais de 80% do que entra na conta",
     lambda h, a: h["mov_saidas_sobre_entradas"] > 0.8,
     "Sem folga no orçamento, qualquer parcela nova vira atraso."),
    ("risco", "8+ consultas ao CPF em 90 dias", "com 8 ou mais consultas ao CPF nos últimos 90 dias",
     lambda h, a: h["consultas_90_dias"] >= 8,
     "Busca intensa por crédito na praça. Até 7 consultas o risco é normal."),
    ("risco", "Renda declarada inflada", "com renda declarada maior que o dobro das entradas reais na conta",
     lambda h, a: h["renda_decl_sobre_real"] > 2,
     "A movimentação da conta desmente a renda informada no cadastro."),
    ("risco", "Pedido acima de 6x as entradas", "que pedem mais de 6 vezes o que entra por mês na conta",
     lambda h, a: h["valor_solicitado"] / h["mov_entradas_med"] > 6,
     "Aqui o problema é o cliente, não só a parcela: mesmo com a parcela entre 30% e 50% da sobra, esse grupo deu cerca de "
     "50% de calote, contra 11% a 19% de quem pediu menos de 6x. Reduzir o valor não resolve; por isso é corte, não teto (v3)."),
    ("risco", "Dívidas fora acima de 35% das entradas", "com parcelas em outros bancos acima de 35% do que entra na conta",
     lambda h, a: h["parcelas_outras_instituicoes"] / h["mov_entradas_med"] > 0.35,
     "Medida contra o que de fato entra na conta, a dívida em outros bancos tem um degrau nítido em 35%. "
     "A mesma conta contra a renda declarada quase não separa bons de maus pagadores (v3)."),
    ("risco", "Pico de entradas antes do pedido", "sem outros sinais de alerta, mas com entradas nos 3 meses antes do pedido 35% ou mais acima da média dos meses anteriores",
     lambda h, a: (h["mov_tendencia_entradas"] > 1.35) & ~_alerta(h, incluir_pico=False),
     "A conta \"engorda\" pouco antes do pedido: a movimentação recente não representa a renda de verdade. Entre 1,2x e 1,35x o risco é normal."),
    ("risco", "Entradas instáveis", "sem sinais de alerta, mas com entradas instáveis (variação mensal acima de 30%)",
     lambda h, a: (h["mov_entradas_cv"] > 0.3) & ~a,
     "Renda irregular quase dobra o risco em relação aos clientes sem sinais de alerta (16% contra 8%) e fica perto do ponto "
     "em que emprestar deixa de dar lucro. Entra no modelo, não é corte."),
    ("neutro", "Dívidas fora acima de 30% da renda", "sem sinais de alerta (dívida abaixo de 35% das entradas), mas com dívidas em outros bancos acima de 30% da renda declarada",
     lambda h, a: (h["divida_outras_sobre_renda"] > 0.3) & ~a,
     "Parece risco, mas não é: contra a renda declarada a dívida parece alta, mas, enquanto fica abaixo de 35% do que entra "
     "na conta, o calote é menor que o dos clientes sem alerta. O que importa é a dívida sobre as entradas reais (v3)."),
    ("oportunidade", "Score 450 a 600 sem alertas", "com score entre 450 e 600 e sem sinais de alerta",
     lambda h, a: (h["score"] >= 450) & (h["score"] <= 600) & ~a & (h["parcela_sobre_sobra"] <= 0.5),
     "A política atual nega todos. Score baixo, sozinho, quase não prevê calote nesta base."),
    ("oportunidade", "Renda até R$ 2.000 sem alertas", "com renda declarada entre R$ 1.500 e R$ 2.000 e sem sinais de alerta",
     lambda h, a: (h["renda_declarada"] >= 1500) & (h["renda_declarada"] <= 2000) & ~a & (h["parcela_sobre_sobra"] <= 0.5),
     "A política atual nega todos. Com parcela proporcional à renda, pagam como a média."),
    ("oportunidade", "1 restrição sem alertas", "com 1 restrição ativa e sem sinais de alerta",
     lambda h, a: (h["restricoes_ativas"] == 1) & ~a & (h["parcela_sobre_sobra"] <= 0.5),
     "A política atual nega todos. Pagam, mas atrasam mais: cerca de um terço tem alguma parcela em atraso, contra cerca de 22% dos demais."),
    ("oportunidade", "Aposentados", "aposentados sem sinais de alerta",
     lambda h, a: (h["tipo_vinculo"] == "aposentado") & ~a,
     "Renda estável: o grupo de menor risco da base."),
    ("neutro", "Conta aberta há 3 meses ou menos", "sem sinais de alerta e com conta na Fortuna aberta há 3 meses ou menos",
     lambda h, a: (h["meses_conta"] <= 3) & ~a & (h["parcela_sobre_sobra"] <= 0.5),
     "Parece risco, mas não é. Na base inteira o grupo tem calote alto, mas por causa dos sinais de alerta que muitos deles têm. Sem os sinais, paga como a média. Por isso não é corte."),
    ("neutro", "Score acima de 800", "sem sinais de alerta e com score acima de 800",
     lambda h, a: (h["score"] > 800) & ~a & (h["parcela_sobre_sobra"] <= 0.5),
     "Score alto não protege. Esse grupo paga igual ao de score 600 a 800, então o score pesa pouco na decisão."),
]


def padroes_negocio(h: pd.DataFrame, novos: pd.DataFrame | None = None) -> tuple[list[dict], dict]:
    """Padrões consolidados para o painel. Taxas por Kaplan-Meier no histórico; contagem também nos novos
    (nos novos, as medidas de parcela usam o valor solicitado)."""
    base_pd, base_n = taxa(h)
    a = _alerta(h)
    pd_limpo, n_limpo = taxa(h[~a & (h["parcela_sobre_sobra"] <= 0.5)])
    if novos is not None:
        nv = novos.reset_index(drop=True).copy()
        nv["valor_aprovado"] = nv["valor_solicitado"]
        nv = preparar(nv)
        an = _alerta(nv)
    out = []
    for tipo, titulo, sujeito, fn, leitura in SPECS:
        mask = fn(h, a)
        g = h[mask.values]
        pd_, n = taxa(g)
        atraso = float(g.loc[~g["calote_obs"] & (g["frac_vencida"] >= 0.5), "atraso_obs"].mean()) if n else np.nan
        n_novos = None
        if novos is not None:
            mn = fn(nv, an)
            n_novos = int(mn.sum()) if mn is not None else None
        out.append({"tipo": tipo, "titulo": titulo, "sujeito": sujeito, "pd": pd_, "n": n, "pd_media": base_pd,
                    "depende_valor": "sobra" in titulo.lower() or "renda declarada" in titulo.lower() and "Reduzidos" in titulo,
                    "lift": pd_ / base_pd if base_pd else np.nan, "leitura": leitura, "taxa_atraso": atraso,
                    "n_novos": n_novos})
    return out, {"pd_media": base_pd, "n": base_n, "pd_sem_alerta": pd_limpo, "n_sem_alerta": n_limpo}


def onde_a_politica_atual_erra(h: pd.DataFrame) -> list[dict]:
    """Medição direta com desfechos reais: piloto aprovou gente que a política atual negaria."""
    elegivel_atual = (h["score"] > 600) & (h["renda_declarada"] > 2000) & (h["restricoes_ativas"] == 0)
    alerta = _alerta(h) | (h["parcela_sobre_sobra"] > 0.5)
    piloto_fora = (h["politica_aplicada"] == "piloto") & ~elegivel_atual
    grupos = [
        ("Clientes que a política atual aprovaria (aprovados pela atual ou pelo piloto, dentro das regras atuais)", elegivel_atual),
        ("…desses, com sinal de alerta ou parcela > 50% da sobra (a atual aprova; a proposta nega ou reduz o valor)", elegivel_atual & alerta),
        ("…desses, sem sinal de alerta", elegivel_atual & ~alerta),
        ("Aprovados no piloto que a política atual negaria", piloto_fora),
        ("…desses, sem sinal de alerta (a atual nega, a proposta aprova)", piloto_fora & ~alerta),
        ("…desses, com sinal de alerta", piloto_fora & alerta),
    ]
    out = []
    for desc, mask in grupos:
        g = h[mask]
        pd_, n = taxa(g)
        out.append({"grupo": desc, "pd": pd_, "n": n, "valor_total": float(g["valor_aprovado"].sum())})
    return out
