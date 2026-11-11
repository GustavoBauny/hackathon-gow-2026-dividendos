"""Painel de experimentação (painel/app.py), testado com o AppTest do Streamlit.

Isolamento: o painel lê os artefatos de FORTUNA_DADOS (aqui, uma cópia de data/) e grava/lê a
aprovação em FORTUNA_POLITICA_APROVADA (aqui, um arquivo temporário). Nenhum teste escreve em
data/ nem cria politica_aprovada.json na raiz do repositório.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pandas as pd
import pytest
from streamlit.proto.Metric_pb2 import Metric as MetricProto
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parent.parent
APP = str(RAIZ / "painel" / "app.py")
ARTEFATOS = ["novos_base.parquet", "hist_base.parquet", "modelo_risco.json", "resumo_execucao.json", "padroes.json"]
APROVADA_RAIZ = RAIZ / "politica_aprovada.json"

pytestmark = pytest.mark.skipif(any(not (RAIZ / "data" / f).exists() for f in ARTEFATOS),
                                reason="artefatos ausentes: rode python gerar_decisoes.py")


# ------------------------------------------------------------------ ambiente isolado
@pytest.fixture(scope="module")
def dados_copia(tmp_path_factory) -> Path:
    """Cópia somente-leitura (por convenção) dos artefatos do pipeline."""
    destino = tmp_path_factory.mktemp("dados")
    for f in ARTEFATOS:
        shutil.copy2(RAIZ / "data" / f, destino / f)
    return destino


@pytest.fixture
def dados_editaveis(dados_copia, tmp_path, monkeypatch) -> Path:
    """Cópia própria do teste, que ele pode alterar."""
    destino = tmp_path / "dados"
    shutil.copytree(dados_copia, destino)
    monkeypatch.setenv("FORTUNA_DADOS", str(destino))
    return destino


@pytest.fixture(autouse=True)
def aprovada(monkeypatch, dados_copia, tmp_path) -> Path:
    """Caminho temporário da política aprovada; falha se algum teste criar o arquivo na raiz."""
    existia = APROVADA_RAIZ.exists()
    caminho = tmp_path / "politica_aprovada.json"
    monkeypatch.setenv("FORTUNA_DADOS", str(dados_copia))
    monkeypatch.setenv("FORTUNA_POLITICA_APROVADA", str(caminho))
    yield caminho
    if not existia and APROVADA_RAIZ.exists():
        APROVADA_RAIZ.unlink()
        pytest.fail("o teste gravou politica_aprovada.json na raiz do repositório")


@pytest.fixture(scope="module")
def padrao(dados_copia, tmp_path_factory) -> AppTest:
    """Uma execução do painel com a proposta da IA, compartilhada pelos testes que só leem a tela."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("FORTUNA_DADOS", str(dados_copia))
        mp.setenv("FORTUNA_POLITICA_APROVADA", str(tmp_path_factory.mktemp("apv") / "politica_aprovada.json"))
        return rodar()


def rodar() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def editar_json(caminho: Path, **mudancas) -> None:
    d = json.loads(caminho.read_text(encoding="utf-8"))
    d.update(mudancas)
    caminho.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def textos(bloco) -> list[str]:
    return [m.value for m in bloco.markdown] + [c.value for c in bloco.caption]


# ------------------------------------------------------------------ isolamento (pré-requisito dos demais testes)
def test_painel_le_a_aprovacao_do_caminho_configurado(aprovada):
    aprovada.write_text(json.dumps({"aprovado_por": "Fulana de Tal", "aprovado_em": "2026-01-02T03:04:05",
                                    "comentario": "", "parametros": {}}), encoding="utf-8")
    at = rodar()
    assert any("Fulana de Tal" in c.value for c in at.sidebar.caption)


def test_painel_le_os_artefatos_da_pasta_configurada(dados_editaveis):
    editar_json(dados_editaveis / "resumo_execucao.json", gerado_em="2031-01-02T03:04:05")
    at = rodar()
    assert any("2031-01-02T03:04:05" in t for t in textos(at.tabs[4]))


def por_rotulo(elementos, rotulo: str):
    achados = [e for e in elementos if e.label == rotulo]
    assert achados, f"nenhum elemento com rótulo {rotulo!r}; há: {[e.label for e in elementos]}"
    return achados[0]


def expander_com(at: AppTest, trecho: str):
    achados = [e for e in at.sidebar.expander if trecho in e.label]
    assert achados, f"nenhum expander com {trecho!r}; há: {[e.label for e in at.sidebar.expander]}"
    return achados[0]


def passo_4(at: AppTest) -> str:
    return next(m.value for m in at.tabs[1].markdown if m.value.startswith("**4."))


# ------------------------------------------------------------------ PAINEL-01: barra lateral guarda os ajustes
def test_segundo_ajuste_do_slider_vale():
    at = rodar()
    teto = por_rotulo(at.sidebar.slider, "Parcela máxima / sobra mensal")
    teto.set_value(0.30).run()
    por_rotulo(at.sidebar.slider, "Parcela máxima / sobra mensal").set_value(0.20).run()
    assert "a parcela cabe em 20% da sobra mensal" in passo_4(at)


def test_rotulo_da_regra_acompanha_o_ajuste_na_mesma_execucao():
    at = rodar()
    at.sidebar.checkbox(key="a_pedido_excessivo").uncheck().run()
    assert expander_com(at, "pede mais de 6x").label.startswith("⏸️")


def test_voltar_a_proposta_da_ia_reativa_a_regra_desligada():
    at = rodar()
    at.sidebar.checkbox(key="a_pedido_excessivo").uncheck().run()
    por_rotulo(at.sidebar.button, "Voltar à proposta da IA").click().run()
    assert at.sidebar.checkbox(key="a_pedido_excessivo").value is True
    assert any("pede mais de 6x" in m.value for m in at.tabs[1].markdown)


def test_voltar_a_proposta_da_ia_restaura_o_teto_da_sobra():
    at = rodar()
    por_rotulo(at.sidebar.slider, "Parcela máxima / sobra mensal").set_value(0.20).run()
    por_rotulo(at.sidebar.button, "Voltar à proposta da IA").click().run()
    assert "a parcela cabe em 45% da sobra mensal" in passo_4(at)


# ------------------------------------------------------------------ PAINEL-02: perdas no cabeçalho aparecem como queda
REGRAS_PASSO_3 = ["gasta_tudo", "renda_inflada", "pedido_excessivo", "divida_alta", "entradas_instaveis"]
DESCE, SOBE, SEM_SETA = (MetricProto.MetricDirection.DOWN, MetricProto.MetricDirection.UP,
                         MetricProto.MetricDirection.NONE)


def metrica(at: AppTest, rotulo: str):
    return por_rotulo(at.metric, rotulo)


def test_perda_de_valor_no_cabecalho_aparece_como_queda():
    at = rodar()
    # Renda declarada máxima nos novos é R$ 28.450: com o piso em R$ 1 milhão a nova política nega todos,
    # então o valor aprovado cai de "o da política atual" para zero.
    at.sidebar.number_input(key="l_renda_min").set_value(1_000_000.0).run()
    m = metrica(at, "Valor total aprovado")
    assert m.proto.delta.startswith("-R$ ")
    assert m.proto.direction == DESCE


def test_ganho_de_valor_no_cabecalho_aparece_como_alta():
    at = rodar()
    # Sem sinais de alerta, sem tetos e sem modelo, a nova política aprova todo pedido que a atual aprova
    # (a faixa do passo 2 contém a da atual) no valor pedido, que é >= o valor da atual, e ainda aprova mais.
    for k in [f"a_{r}" for r in REGRAS_PASSO_3] + ["cap_sobra_on", "cap_renda_on", "mod_on"]:
        at.sidebar.checkbox(key=k).uncheck()
    at.run()
    m = metrica(at, "Valor total aprovado")
    assert m.proto.delta.startswith("+R$ ")
    assert m.proto.direction == SOBE


def test_calote_esperado_mostra_o_valor_atual_sem_seta(padrao):
    m = metrica(padrao, "Calote esperado dos aprovados")
    assert m.proto.delta.startswith("atual: ")
    assert m.proto.direction == SEM_SETA


# ------------------------------------------------------------------ PAINEL-07: histórico da barra lateral = base da aba 1
def expander_da_regra(at: AppTest, id_regra: str):
    achados = [e for e in at.sidebar.expander if any(c.key == f"a_{id_regra}" for c in e.checkbox)]
    assert achados, f"nenhum expander com a regra {id_regra}"
    return achados[0]


def pct1(x: float) -> str:
    return f"{x * 100:.1f}".replace(".", ",") + "%"


@pytest.mark.parametrize("id_regra, id_padrao", [("pedido_excessivo", "P04"), ("divida_alta", "P05"),
                                                 ("entradas_instaveis", "P07")])
def test_historico_da_regra_usa_a_mesma_base_da_aba_1(padrao, dados_copia, id_regra, id_padrao):
    p = next(p for p in json.loads((dados_copia / "padroes.json").read_text(encoding="utf-8"))["padroes"]
             if p["id"] == id_padrao)
    esperado = (f"Histórico: {p['n_aprovados']} contratos aprovados no grupo, inadimplência "
                f"{pct1(p['taxa_segmento'])} contra {pct1(p['taxa_referencia'])} dos demais")
    legendas = [c.value for c in expander_da_regra(padrao, id_regra).caption]
    assert any(c.startswith(esperado) for c in legendas), legendas


@pytest.mark.parametrize("id_regra", ["restricoes", "score_min", "renda_min"])
def test_grupo_nunca_aprovado_diz_que_nao_ha_dados(padrao, id_regra):
    legendas = [c.value for c in expander_da_regra(padrao, id_regra).caption]
    assert "Nunca aprovado no histórico: não há dados de pagamento para este grupo." in legendas


# ------------------------------------------------------------------ PAINEL-03: desligar regra do passo 3 sem efeito
# Todo pedido do grupo P04 (pede mais de 6x as entradas) tem chance de calote de pelo menos
# 7,6% x 4,89 x 0,73 (aposentado, único fator abaixo de 1) = 27%, acima do ponto de equilíbrio (~17%):
# o modelo do passo 5 nega todos eles.
def test_passo_3_mostra_quantos_negados_o_modelo_tambem_negaria(padrao):
    linha = next(m.value for m in padrao.tabs[1].markdown if "pede mais de 6x" in m.value)
    achado = re.search(r"negados: ([\d.]+) · o modelo do passo 5 também negaria ([\d.]+)", linha)
    assert achado, linha
    assert achado.group(1) == achado.group(2)


def test_regra_desligada_explica_que_o_modelo_negaria_o_grupo(dados_copia):
    novos = pd.read_parquet(dados_copia / "novos_base.parquet")
    n_grupo = int((novos["pedido_sobre_entradas"] > 6).sum())
    at = rodar()
    at.sidebar.checkbox(key="a_pedido_excessivo").uncheck().run()
    legendas = [c.value for c in expander_da_regra(at, "pedido_excessivo").caption]
    assert f"Pedidos novos no grupo: {n_grupo}." in legendas
    assert any(f"o modelo do passo 5 negaria todos esses {n_grupo} pedidos mesmo sem esta regra" in c for c in legendas), \
        legendas


# ------------------------------------------------------------------ R10: dados regravados pelo pipeline aparecem no painel
def adiantar_relogio(caminho: Path) -> None:
    """Garante mtime diferente do anterior, como numa nova execução do pipeline."""
    st_ = caminho.stat()
    os.utime(caminho, ns=(st_.st_atime_ns, st_.st_mtime_ns + 5_000_000_000))


def test_resumo_regravado_aparece_na_execucao_seguinte(dados_editaveis):
    at = rodar()
    resumo = dados_editaveis / "resumo_execucao.json"
    editar_json(resumo, gerado_em="2032-05-06T07:08:09")
    adiantar_relogio(resumo)
    at.run()
    assert any("2032-05-06T07:08:09" in t for t in textos(at.tabs[4]))


def test_decisoes_sao_recalculadas_quando_os_pedidos_novos_mudam(dados_editaveis):
    at = rodar()
    arq = dados_editaveis / "novos_base.parquet"
    pd.read_parquet(arq).head(100).to_parquet(arq)
    adiantar_relogio(arq)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert metrica(at, "Pedidos aprovados").value.endswith(" de 100")


def test_recarregar_dados_le_de_novo_mesmo_sem_mudar_a_data_do_arquivo(dados_editaveis):
    at = rodar()
    resumo = dados_editaveis / "resumo_execucao.json"
    antes = resumo.stat()
    editar_json(resumo, gerado_em="2033-01-01T00:00:00")
    os.utime(resumo, ns=(antes.st_atime_ns, antes.st_mtime_ns))
    por_rotulo(at.sidebar.button, "Recarregar dados").click().run()
    assert any("2033-01-01T00:00:00" in t for t in textos(at.tabs[4]))


# ------------------------------------------------------------------ PAINEL-13: fluxo de aprovação
AVISO_DESATUALIZADO = "O arquivo de decisões foi gerado antes desta aprovação: rode python gerar_decisoes.py"
CONFIRMACAO = "Revisei o impacto e quero aprovar esta versão"


def gravar_aprovacao(caminho: Path, aprovado_em: str) -> None:
    caminho.write_text(json.dumps({"aprovado_por": "Ana Analista", "aprovado_em": aprovado_em, "comentario": "",
                                   "parametros": {}}), encoding="utf-8")


def avisos(at: AppTest) -> list[str]:
    return [w.value for w in at.sidebar.warning]


def test_legenda_diz_que_a_versao_aprovada_vale_na_proxima_execucao(aprovada):
    gravar_aprovacao(aprovada, "2026-01-02T03:04:05")
    at = rodar()
    assert any(c.value.startswith("Versão aprovada (usada na próxima execução do pipeline)") for c in at.sidebar.caption)


def test_avisa_quando_a_aprovacao_e_mais_nova_que_o_arquivo_de_decisoes(aprovada, dados_editaveis):
    editar_json(dados_editaveis / "resumo_execucao.json", gerado_em="2026-01-01T00:00:00",
                politica_usada="politica_aprovada.json")
    gravar_aprovacao(aprovada, "2026-02-01T00:00:00")
    at = rodar()
    assert any(AVISO_DESATUALIZADO in a for a in avisos(at)), avisos(at)


def test_aprovar_com_confirmacao_grava_a_politica_ajustada(aprovada):
    at = rodar()
    at.sidebar.checkbox(key="a_pedido_excessivo").uncheck().run()
    por_rotulo(at.sidebar.text_input, "Seu nome").set_value("Ana Analista").run()
    por_rotulo(at.sidebar.checkbox, CONFIRMACAO).check().run()
    por_rotulo(at.sidebar.button, "Aprovar esta versão da política").click().run()
    gravado = json.loads(aprovada.read_text(encoding="utf-8"))
    assert gravado["aprovado_por"] == "Ana Analista"
    regra = next(r for r in gravado["parametros"]["regras"] if r["id"] == "pedido_excessivo")
    assert regra["ativa"] is False


def test_nao_avisa_quando_o_pipeline_ja_rodou_com_a_aprovacao(aprovada, dados_editaveis):
    editar_json(dados_editaveis / "resumo_execucao.json", gerado_em="2026-03-01T00:00:00",
                politica_usada="politica_aprovada.json")
    gravar_aprovacao(aprovada, "2026-02-01T00:00:00")
    at = rodar()
    assert not any(AVISO_DESATUALIZADO in a for a in avisos(at)), avisos(at)


def test_avisa_quando_o_pipeline_rodou_sem_a_versao_aprovada(aprovada, dados_editaveis):
    editar_json(dados_editaveis / "resumo_execucao.json", gerado_em="2026-03-01T00:00:00",
                politica_usada="proposta da IA (sem aprovação gravada)")
    gravar_aprovacao(aprovada, "2026-02-01T00:00:00")
    at = rodar()
    assert any(AVISO_DESATUALIZADO in a for a in avisos(at)), avisos(at)


def test_aprovar_fica_bloqueado_sem_confirmacao():
    at = rodar()
    por_rotulo(at.sidebar.text_input, "Seu nome").set_value("Ana Analista").run()
    assert por_rotulo(at.sidebar.button, "Aprovar esta versão da política").disabled


# ------------------------------------------------------------------ PAINEL-12: aba de execução mostra a resiliência
BUREAU_DO_CACHE = {"chamadas_http": 0, "sucesso": 0, "respostas_503": 0, "timeouts": 0, "erros_conexao": 0, "404": 0,
                   "falha_definitiva": 0, "lidos_do_cache": 2000, "status": {"ok": 2000}}


def test_execucao_mostra_as_novas_tentativas_da_consulta_original(dados_editaveis):
    editar_json(dados_editaveis / "resumo_execucao.json",
                bureau={**BUREAU_DO_CACHE, "tentativas_por_cliente": {"1": 1897, "2": 98, "3": 4, "4": 1},
                        "clientes_com_retry": 103})
    at = rodar()
    assert ("Na consulta original: 103 clientes precisaram de nova tentativa (até 4); todos responderam. "
            "Esta execução leu do cache.") in textos(at.tabs[4])


def test_execucao_sem_detalhe_das_tentativas_diz_que_leu_do_cache(dados_editaveis):
    editar_json(dados_editaveis / "resumo_execucao.json", bureau=BUREAU_DO_CACHE)
    at = rodar()
    assert any("Esta execução leu do cache." in t for t in textos(at.tabs[4]))


def test_validacao_do_arquivo_aparece_como_uma_frase(dados_editaveis):
    editar_json(dados_editaveis / "resumo_execucao.json",
                validacao={"ok": True, "linhas": 2000, "pedidos_com_decisao": 2000, "aprovados": 1287, "negados": 713,
                           "valor_total_aprovado": 9039987.81, "problemas": []})
    at = rodar()
    assert not at.tabs[4].json
    assert ("Validação do arquivo: 2.000 linhas, uma decisão para cada um dos 2.000 pedidos; 1.287 aprovados e "
            "713 negados, R$ 9.039.988 aprovados no total. Nenhum problema encontrado.") in textos(at.tabs[4])


def test_validacao_com_problemas_lista_os_problemas(dados_editaveis):
    editar_json(dados_editaveis / "resumo_execucao.json",
                validacao={"ok": False, "problemas": ["arquivo começa com BOM", "linha 7: decisao inválida 'X'"]})
    at = rodar()
    assert any("Problemas encontrados: arquivo começa com BOM; linha 7: decisao inválida 'X'." in t
               for t in textos(at.tabs[4]))


# ------------------------------------------------------------------ PAINEL-09: consulta de um pedido
@pytest.fixture(scope="module")
def gasta_tudo(dados_copia) -> pd.Series:
    """Primeiro pedido (por id) que passa no passo 2, tem saídas >= 90% das entradas (regra gasta_tudo) e não cai
    em nenhuma outra regra do passo 3: com a regra gasta_tudo desligada, só a regra de calote certo o pega."""
    n = pd.read_parquet(dados_copia / "novos_base.parquet").sort_values("id_pedido")
    passo_2 = (n["score"] > 450) & (n["renda_declarada"] > 1500) & (n["restricoes_ativas"] < 2)
    outras_3 = ((n["renda_decl_sobre_real"] > 2) | (n["pedido_sobre_entradas"] > 6)
                | (n["outras_sobre_entradas"] > 0.35) | (n["mov_entradas_cv"] > 0.35))
    alvo = n[passo_2 & (n["mov_saidas_sobre_entradas"] >= 0.9) & ~outras_3 & (n["valor_solicitado"] >= 500)]
    assert len(alvo), "a base não tem pedido com esse perfil"
    return alvo.iloc[0]


def consultar(at: AppTest, id_pedido: str) -> AppTest:
    por_rotulo(at.selectbox, "Pedido").set_value(id_pedido).run()
    return at


def linha_de_risco(at: AppTest) -> str:
    return next(m.value for m in at.tabs[3].markdown if m.value.startswith("**Risco"))


def test_pedido_negado_no_passo_3_diz_que_o_modelo_nao_foi_usado(gasta_tudo):
    at = consultar(rodar(), gasta_tudo["id_pedido"])
    assert "Negado no passo 3: a estimativa do modelo não foi usada" in linha_de_risco(at)


@pytest.fixture(scope="module")
def renda_inflada(dados_copia) -> pd.Series:
    """Primeiro pedido (por id) com renda declarada > 2x as entradas, que passa no passo 2, não cai em outra regra
    do passo 3 e tem sobra para pelo menos R$ 500: com a regra desligada, chega ao passo 5 e só a regra de calote
    certo o pega. (O perfil 'gasta tudo' sem sobra já para no passo 4, pela trava fixa de 50% da sobra.)"""
    n = pd.read_parquet(dados_copia / "novos_base.parquet").sort_values("id_pedido")
    passo_2 = (n["score"] > 450) & (n["renda_declarada"] > 1500) & (n["restricoes_ativas"] < 2)
    outras_3 = ((n["mov_saidas_sobre_entradas"] >= 0.9) | (n["pedido_sobre_entradas"] > 6)
                | (n["outras_sobre_entradas"] > 0.35) | (n["mov_entradas_cv"] > 0.35))
    cabe = n["sobra"] * 0.45 * 4.5 >= 500   # parcela de 45% da sobra paga ao menos R$ 500 em 6 meses
    alvo = n[passo_2 & (n["renda_decl_sobre_real"] > 2) & ~outras_3 & cabe & (n["valor_solicitado"] >= 500)]
    assert len(alvo), "a base não tem pedido com esse perfil"
    return alvo.iloc[0]


def test_pedido_em_regra_de_calote_certo_explica_o_risco_sem_conta_que_nao_fecha(renda_inflada):
    at = rodar()
    at.sidebar.checkbox(key="a_renda_inflada").uncheck()
    at.run()
    linha = linha_de_risco(consultar(at, renda_inflada["id_pedido"]))
    assert "regra de calote certo" in linha
    assert "(base)" not in linha


def test_valor_do_cliente_formatado_pelo_tipo_de_cada_coluna(gasta_tudo):
    at = consultar(rodar(), gasta_tudo["id_pedido"])
    g = gasta_tudo

    def br(x: float, casas: int) -> str:
        return f"{x:,.{casas}f}".replace(",", "_").replace(".", ",").replace("_", ".")

    esperado = ["ok",                                              # bureau
                br(g["restricoes_ativas"], 0),                     # contagem
                br(g["score"], 0),                                 # pontuação inteira
                "R$ " + br(g["renda_declarada"], 0),               # dinheiro
                br(g["mov_saidas_sobre_entradas"] * 100, 1) + "%",  # proporção
                br(g["renda_decl_sobre_real"], 2) + "x",           # múltiplo
                br(g["pedido_sobre_entradas"], 2) + "x",           # múltiplo
                br(g["outras_sobre_entradas"] * 100, 1) + "%",     # proporção
                br(g["mov_entradas_cv"] * 100, 1) + "%"]           # proporção
    assert at.tabs[3].dataframe[0].value["Valor do cliente"].tolist() == esperado


# ------------------------------------------------------------------ PAINEL-10: números em formato brasileiro
MILHAR = r"-?\d{1,3}(?:\.\d{3})*"   # 7 | 1.287 | -31.250 (nunca 1287 nem 1,287)


def br(x: float, casas: int = 0) -> str:
    return f"{x:,.{casas}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def modelo_json(dados: Path) -> dict:
    return json.loads((dados / "modelo_risco.json").read_text(encoding="utf-8"))


def test_cabecalho_conta_pedidos_com_separador_de_milhar(padrao):
    assert re.fullmatch(rf"{MILHAR} de 2\.000", metrica(padrao, "Pedidos aprovados").value)


def test_passo_6_conta_aprovados_com_separador_de_milhar(padrao):
    passo_6 = next(m.value for m in padrao.tabs[1].markdown if m.value.startswith("**6."))
    assert re.search(rf"Aprovados: {MILHAR}\.\*", passo_6), passo_6


def test_texto_da_regra_mostra_reais_em_formato_brasileiro(padrao):
    assert any("renda declarada até R$ 1.500 (nunca aprovada no histórico)" in m.value for m in padrao.tabs[1].markdown)


def test_limiar_decimal_da_regra_usa_virgula():
    at = rodar()
    at.sidebar.number_input(key="l_renda_inflada").set_value(2.5).run()
    assert any("renda declarada mais de 2,5x o que entra na conta" in m.value for m in at.tabs[1].markdown)


def test_margem_minima_do_passo_5_usa_virgula(padrao):
    passo_5 = next(m.value for m in padrao.tabs[1].markdown if m.value.startswith("**5."))
    assert "menor que 1,0% do valor" in passo_5


def test_contagens_grandes_da_regra_usam_separador_de_milhar(dados_copia):
    novos = pd.read_parquet(dados_copia / "novos_base.parquet")
    # score vai até 1000: todos caem no grupo, mas a regra de restrições (antes no passo 2) nega os seus primeiro
    negados_score = len(novos) - int((novos["restricoes_ativas"] >= 2).sum())
    at = rodar()
    at.sidebar.number_input(key="l_score_min").set_value(1000.0).run()
    legendas = [c.value for c in expander_da_regra(at, "score_min").caption]
    assert f"Pedidos novos no grupo: {br(len(novos))}." in legendas
    assert any(re.match(r"Histórico: \d{1,3}(\.\d{3})+ contratos", c) for c in legendas), legendas
    assert any(f"negados: {br(negados_score)}*" in m.value for m in at.tabs[1].markdown)


def test_tabela_de_multiplicadores_com_duas_casas_decimais(padrao, dados_copia):
    fatores = {k: v for k, v in modelo_json(dados_copia)["diagnostico"]["calote"]["fatores"].items() if k != "const"}
    tabela = next(d.value for d in padrao.tabs[1].dataframe if "Multiplica o risco por" in d.value.columns)
    assert tabela["Multiplica o risco por"].tolist() == [br(v["rr"], 2) for v in fatores.values()]
    assert tabela["Intervalo de 95%"].tolist() == [f"{br(v['ic95'][0], 2)} a {br(v['ic95'][1], 2)}"
                                                   for v in fatores.values()]


def test_legenda_do_modelo_de_atraso_em_formato_brasileiro(padrao, dados_copia):
    d = modelo_json(dados_copia)["diagnostico"]
    legenda = next(c.value for c in padrao.tabs[1].caption if c.value.startswith("Atraso:"))
    assert f"Modelo ajustado em {br(d['calote']['n_contratos'])} contratos ({br(d['calote']['calotes'])} calotes)" in legenda
    assert f"(odds) por {br(d['atraso']['fatores']['divida_alta']['odds_ratio'], 1)}" in legenda


def test_aba_1_conta_pedidos_do_historico_com_separador_de_milhar(padrao, dados_copia):
    p01 = json.loads((dados_copia / "padroes.json").read_text(encoding="utf-8"))["padroes"][0]
    assert any(f"**Histórico:** {br(p01['n_hist'])} pedidos no grupo" in m.value for m in padrao.tabs[0].markdown)


def test_tabelas_do_impacto_em_formato_brasileiro(padrao):
    comparacao, cruzada = padrao.tabs[2].dataframe[0].value, padrao.tabs[2].dataframe[1].value
    for celula in list(comparacao.to_numpy().ravel()) + list(cruzada.to_numpy().ravel()):
        assert isinstance(celula, str) and re.fullmatch(MILHAR, celula), celula


def test_aba_de_execucao_conta_clientes_com_separador_de_milhar(dados_editaveis):
    editar_json(dados_editaveis / "resumo_execucao.json", bureau=BUREAU_DO_CACHE)
    assert metrica(rodar(), "Clientes consultados").value == "2.000"


# ------------------------------------------------------------------ PAINEL-11: rótulos de negócio nos controles
@pytest.mark.parametrize("id_regra, rotulo", [
    ("restricoes", "Negar a partir de quantas restrições"),
    ("score_min", "Negar score até"),
    ("renda_min", "Negar renda declarada até (R$)"),
    ("gasta_tudo", "Negar quando saídas ÷ entradas ≥"),
    ("renda_inflada", "Negar quando renda declarada ÷ entradas >"),
    ("pedido_excessivo", "Negar quando pedido ÷ entradas mensais >"),
    ("divida_alta", "Negar quando parcelas em outras instituições ÷ entradas >"),
    ("entradas_instaveis", "Negar quando a variação das entradas >"),
])
def test_limiar_da_regra_tem_rotulo_de_negocio(padrao, id_regra, rotulo):
    assert padrao.sidebar.number_input(key=f"l_{id_regra}").label == rotulo
