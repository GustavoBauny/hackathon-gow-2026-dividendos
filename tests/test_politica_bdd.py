"""Passos dos cenários de tests/features/politica.feature.

O modelo de risco usado aqui tem coeficientes fixos (os multiplicadores do painel), para que o
cenário dependa só das regras da política e não do ajuste no histórico.
"""
import math

import numpy as np
import pandas as pd
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from features import parcela_price
from politica import Parametros, politica_nova
from risco import ModeloRisco

scenarios("politica.feature")


def brl(texto: str) -> float:
    return float(texto.replace(".", "").replace(",", "."))


@pytest.fixture
def modelo() -> ModeloRisco:
    m = ModeloRisco()
    m.coef_calote = {"const": math.log(0.076), "pedido_excessivo": math.log(4.9), "divida_alta": math.log(3.1),
                     "entradas_instaveis": math.log(2.2), "aposentado": math.log(0.73), "bureau_curto": math.log(1.37)}
    m.coef_atraso = {"const": math.log(0.215 / 0.785), "divida_alta": math.log(2.84), "uma_restricao": math.log(2.46)}
    m.taxas_duras = {"capacidade": 1.0, "saidas": 1.0, "renda_inflada": 0.92}
    return m


@pytest.fixture
def ctx():
    return {"params": Parametros()}


def cliente_referencia(valor=6000.0, prazo=12, entradas=5000.0, saidas=3000.0) -> dict:
    return {
        "id_pedido": "P-TESTE", "valor_solicitado": valor, "prazo_meses": prazo, "renda_declarada": 5000.0,
        "tipo_vinculo": "assalariado", "score": 780, "restricoes_ativas": 0, "parcelas_outras_instituicoes": 0.0,
        "consultas_90_dias": 1, "meses_historico_bureau": 120, "mov_meses": 12, "mov_meses_cheque": 0,
        "mov_entradas_med": entradas, "mov_saidas_med": saidas, "sobra": entradas - saidas,
        "mov_saidas_sobre_entradas": saidas / entradas, "mov_entradas_cv": 0.10,
        "renda_decl_sobre_real": 5000.0 / entradas, "pedido_sobre_entradas": valor / entradas,
        "outras_sobre_entradas": 0.0,
    }


@given(parsers.parse("um pedido do cliente de referência com {campo} igual a {valor:g}"))
def _com_campo(ctx, campo, valor):
    ctx["pedido"] = {**cliente_referencia(), campo: valor}


@given(parsers.parse("um pedido do cliente de referência com {campo} vazio"))
def _campo_vazio(ctx, campo):
    ctx["pedido"] = {**cliente_referencia(), campo: np.nan}


@given(parsers.re(r"um pedido do cliente de referência de R\$ (?P<valor>[\d.,]+) em (?P<prazo>\d+) parcelas$"))
def _valor(ctx, valor, prazo):
    ctx["pedido"] = cliente_referencia(valor=brl(valor), prazo=int(prazo))


@given(parsers.re(r"um pedido do cliente de referência de R\$ (?P<valor>[\d.,]+) em (?P<prazo>\d+) parcelas "
                  r"com entradas de R\$ (?P<entradas>[\d.,]+) e saídas de R\$ (?P<saidas>[\d.,]+)$"))
def _valor_conta(ctx, valor, prazo, entradas, saidas):
    ctx["pedido"] = cliente_referencia(valor=brl(valor), prazo=int(prazo), entradas=brl(entradas), saidas=brl(saidas))


@given("um pedido do cliente de referência com saídas iguais às entradas")
def _sem_sobra(ctx):
    ctx["pedido"] = cliente_referencia(saidas=5000.0)


@given(parsers.parse('o analista desligou a regra "{regra}"'))
def _desliga(ctx, regra):
    ctx["params"].regra(regra).ativa = False


@given(parsers.parse("o analista ajustou o teto da sobra para {teto}"))
def _teto(ctx, teto):
    ctx["params"].teto_parcela_sobre_sobra = None if teto == "desligado" else float(teto)


@when("a política proposta é aplicada")
def _aplica(ctx, modelo):
    ctx["base"] = pd.DataFrame([ctx["pedido"]])
    ctx["dec"] = politica_nova(ctx["base"], modelo, ctx["params"]).iloc[0]


@then(parsers.re(r"o pedido é (?P<decisao>APROVADO|NEGADO) no passo (?P<passo>\d+)$"), converters={"passo": int})
def _decisao_passo(ctx, decisao, passo):
    d = ctx["dec"]
    assert (d["decisao"], int(d["passo"])) == (decisao, passo), d["motivo"]


@then(parsers.re(r"o pedido é (?P<decisao>APROVADO|NEGADO)$"))
def _decisao(ctx, decisao):
    assert ctx["dec"]["decisao"] == decisao, ctx["dec"]["motivo"]


@then(parsers.re(r"o pedido é APROVADO com R\$ (?P<valor>[\d.,]+)$"))
def _aprovado_com(ctx, valor):
    d = ctx["dec"]
    assert (d["decisao"], round(float(d["valor_aprovado"]), 2)) == ("APROVADO", brl(valor)), d["motivo"]


@then(parsers.parse("a parcela aprovada não passa de {pct:d}% da sobra mensal"))
def _parcela_ate(ctx, pct):
    d, p = ctx["dec"], ctx["pedido"]
    assert float(parcela_price(d["valor_aprovado"], p["prazo_meses"])) <= pct / 100 * p["sobra"] + 1e-9


@then(parsers.parse("o pedido é APROVADO com parcela de até {pct:d}% da sobra mensal"))
def _aprovado_parcela_ate(ctx, pct):
    d, p = ctx["dec"], ctx["pedido"]
    assert d["decisao"] == "APROVADO", d["motivo"]
    assert float(parcela_price(d["valor_aprovado"], p["prazo_meses"])) <= pct / 100 * p["sobra"] + 1e-9
