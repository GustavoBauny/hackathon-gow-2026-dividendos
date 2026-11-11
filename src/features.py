"""Engenharia de features: pedido + cadastro + bureau + 12 meses de movimentação da conta."""
import numpy as np
import pandas as pd

TAXA = 0.03
VALOR_MIN, VALOR_MAX = 500.0, 30000.0


def parcela_price(valor, prazo):
    """Parcela pela tabela Price (3% a.m.)."""
    return np.round(np.asarray(valor, float) * TAXA / (1 - (1 + TAXA) ** (-np.asarray(prazo, float))), 2)


def valor_max_por_parcela(parcela_max, prazo):
    """Maior valor cuja parcela Price não passa de parcela_max."""
    return np.asarray(parcela_max, float) * (1 - (1 + TAXA) ** (-np.asarray(prazo, float))) / TAXA


def features_movimentacao(mov: pd.DataFrame) -> pd.DataFrame:
    """Resumo por cliente dos meses de conta anteriores ao pedido."""
    m = mov.sort_values(["id_cliente", "mes_referencia"]).copy()
    m["tem_salario"] = m["entradas_salario"] > 0
    m["usou_cheque"] = m["dias_cheque_especial"] > 0
    m["ordem_desc"] = m.groupby("id_cliente").cumcount(ascending=False)  # 0 = mês mais recente
    g = m.groupby("id_cliente")
    rec = m[m["ordem_desc"] < 3].groupby("id_cliente")
    ant = m[m["ordem_desc"] >= 3].groupby("id_cliente")

    f = pd.DataFrame({
        "mov_meses": g.size(),
        "mov_entradas_med": g["total_entradas"].mean(),
        "mov_entradas_cv": g["total_entradas"].std() / g["total_entradas"].mean().replace(0, np.nan),
        "mov_salario_med": g["entradas_salario"].mean(),
        "mov_frac_meses_salario": g["tem_salario"].mean(),
        "mov_saidas_med": g["total_saidas"].mean(),
        "mov_saldo_medio_med": g["saldo_medio"].mean(),
        "mov_saldo_minimo_min": g["saldo_minimo"].min(),
        "mov_dias_cheque_total": g["dias_cheque_especial"].sum(),
        "mov_meses_cheque": g["usou_cheque"].sum(),
        "mov_frac_meses_cheque": g["usou_cheque"].mean(),
        "mov_dias_cheque_ult3": rec["dias_cheque_especial"].sum(),
        "mov_entradas_ult3": rec["total_entradas"].mean(),
        "mov_entradas_ant": ant["total_entradas"].mean(),
        "mov_saldo_medio_ult3": rec["saldo_medio"].mean(),
    })
    f["mov_saidas_sobre_entradas"] = f["mov_saidas_med"] / f["mov_entradas_med"].replace(0, np.nan)
    f["mov_tendencia_entradas"] = f["mov_entradas_ult3"] / f["mov_entradas_ant"].replace(0, np.nan)
    f["mov_frac_salario_nas_entradas"] = f["mov_salario_med"] / f["mov_entradas_med"].replace(0, np.nan)
    return f.drop(columns=["mov_entradas_ant"])


def montar_base(d: dict[str, pd.DataFrame], bureau_novos: pd.DataFrame | None = None) -> pd.DataFrame:
    """Uma linha por pedido com todas as features. bureau_novos: dados da API (id_cliente + campos)."""
    ped = d["pedidos"].copy()
    cli = d["clientes"].copy()
    bur_hist = d["bureau"].copy()

    base = ped.merge(cli, on="id_cliente", how="left")
    bcols = ["score", "restricoes_ativas", "parcelas_outras_instituicoes", "consultas_90_dias", "meses_historico_bureau"]
    base = base.merge(bur_hist, on="id_pedido", how="left")
    if bureau_novos is not None and len(bureau_novos):
        bn = bureau_novos.set_index("id_cliente")[bcols]
        idx = base["tipo_base"].eq("novo")
        for c in bcols:
            base.loc[idx, c] = base.loc[idx, "id_cliente"].map(bn[c])

    base = base.merge(features_movimentacao(d["movimentacao_mensal"]), left_on="id_cliente", right_index=True, how="left")
    base["mov_meses"] = base["mov_meses"].fillna(0)

    base["idade"] = (base["data_pedido"] - base["data_nascimento"]).dt.days / 365.25
    base["meses_conta"] = (base["data_pedido"] - base["data_abertura_conta"]).dt.days / 30.44
    base["parcela_solicitada"] = parcela_price(base["valor_solicitado"], base["prazo_meses"])
    base["renda_real"] = base["mov_salario_med"].where(base["mov_salario_med"] > 0, base["mov_entradas_med"])
    base["renda_decl_sobre_real"] = base["renda_declarada"] / base["mov_entradas_med"].replace(0, np.nan)
    base["divida_outras_sobre_renda"] = base["parcelas_outras_instituicoes"] / base["renda_declarada"]
    base["uf_regiao_cep"] = base["cep"].str[0]
    return base


def features_do_valor(base: pd.DataFrame, valor) -> pd.DataFrame:
    """Features que dependem do valor concedido (comprometimento de renda)."""
    valor = np.asarray(valor, float)
    parc = parcela_price(valor, base["prazo_meses"].values)
    out = pd.DataFrame(index=base.index)
    out["valor"] = valor
    out["parcela"] = parc
    out["comprometimento"] = parc / base["renda_declarada"].values
    out["comprometimento_total"] = (parc + base["parcelas_outras_instituicoes"].fillna(0).values) / base["renda_declarada"].values
    out["comprometimento_real"] = parc / base["mov_entradas_med"].replace(0, np.nan).values
    out["parcela_sobre_saldo"] = parc / base["mov_saldo_medio_med"].clip(lower=1).values
    return out
