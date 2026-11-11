"""Passos dos cenários de tests/features/arquivo_decisoes.feature."""
import pandas as pd
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from validacao import publicar_csv, validar_csv

scenarios("arquivo_decisoes.feature")


def tabela(datatable) -> pd.DataFrame:
    cab, *linhas = datatable
    return pd.DataFrame(linhas, columns=cab)


@pytest.fixture
def ctx(tmp_path):
    return {"destino": tmp_path / "dividendos_final.csv", "tmp": tmp_path}


@given("os pedidos novos")
def _novos(ctx, datatable):
    n = tabela(datatable)
    n["valor_solicitado"] = n["valor_solicitado"].astype(float)
    ctx["novos"] = n


@given("as decisões")
def _decisoes(ctx, datatable):
    d = tabela(datatable)
    d["valor_aprovado"] = d["valor_aprovado"].astype(float)
    ctx["decisoes"] = d


@given(parsers.parse('um arquivo oficial anterior com o conteúdo "{conteudo}"'))
def _anterior(ctx, conteudo):
    ctx["destino"].write_text(conteudo, encoding="utf-8")


@given(parsers.parse('um arquivo com o conteúdo "{conteudo}"'))
def _arquivo(ctx, conteudo):
    ctx["arquivo"] = ctx["tmp"] / "conferir.csv"
    for escrito, real in (("\\r", "\r"), ("\\n", "\n"), ("\\ufeff", "\ufeff")):
        conteudo = conteudo.replace(escrito, real)
    ctx["arquivo"].write_bytes(conteudo.encode("utf-8"))


@when("o pipeline publica o arquivo")
def _publica(ctx):
    ctx["relatorio"] = publicar_csv(ctx["decisoes"], ctx["destino"], ctx["novos"])


@when("o arquivo é conferido")
def _confere(ctx):
    ctx["relatorio"] = validar_csv(ctx["arquivo"], ctx["novos"])


@then("a publicação é aceita")
def _aceita(ctx):
    assert ctx["relatorio"]["ok"], ctx["relatorio"]["problemas"]


@then("o arquivo oficial é exatamente")
def _exatamente(ctx, docstring):
    assert ctx["destino"].read_bytes() == (docstring.strip() + "\n").encode("utf-8")


@then(parsers.parse('a publicação é recusada com o problema "{trecho}"'))
def _recusada(ctx, trecho):
    r = ctx["relatorio"]
    assert not r["ok"] and any(trecho in p for p in r["problemas"]), r["problemas"]


@then(parsers.parse('o arquivo oficial continua com o conteúdo "{conteudo}"'))
def _continua(ctx, conteudo):
    assert ctx["destino"].read_text(encoding="utf-8") == conteudo


@then(parsers.parse('a conferência aponta o problema "{trecho}"'))
def _aponta(ctx, trecho):
    r = ctx["relatorio"]
    assert not r["ok"] and any(trecho in p for p in r["problemas"]), r["problemas"]
