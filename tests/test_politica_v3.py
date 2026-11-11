"""v3: sinais de alerta de pedido excessivo (P04) e de dívida alta sobre as entradas reais (P05).

Rodar: python -m unittest discover tests   (não precisa do banco)

O cliente de referência é estável: entradas e saídas de R$ 5.000 e R$ 3.000 por mês, renda declarada
de R$ 5.000, score 780, sem restrição. O modelo de risco é um dublê com chance de calote fixa de 5%,
para o teste depender só das regras do passo 3.
"""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from politica import Parametros, politica_nova  # noqa: E402

TAXA_ATRASO = {"com_restricao": 0.50, "divida_fora_alta": 0.39, "sem_restricao": 0.20}


class ModeloRiscoFixo:
    """Chance de calote de 5% para qualquer pedido e valor."""
    def pd_contrato(self, base, valor):
        return np.full(len(np.asarray(valor)), 0.05)


def pedido(**mudancas) -> pd.DataFrame:
    p = {"id_pedido": "P-TESTE", "valor_solicitado": 6000.0, "prazo_meses": 12, "renda_declarada": 5000.0,
         "score": 780, "restricoes_ativas": 0, "consultas_90_dias": 1, "parcelas_outras_instituicoes": 0.0,
         "mov_meses_cheque": 0, "mov_entradas_med": 5000.0, "mov_entradas_ult3": 5000.0, "mov_saidas_med": 3000.0,
         "mov_saidas_sobre_entradas": 0.6, "renda_decl_sobre_real": 1.0, "mov_tendencia_entradas": 1.0}
    p.update(mudancas)
    return pd.DataFrame([p])


def decidir(**mudancas) -> pd.Series:
    return politica_nova(pedido(**mudancas), ModeloRiscoFixo(), TAXA_ATRASO, Parametros()).iloc[0]


class TestPedidoExcessivo(unittest.TestCase):
    """P04: valor PEDIDO acima de 6x o que entra por mês na conta. No histórico, ~50% de calote mesmo
    quando a política atual reduziu o valor (76% reduzidos a até 3x as entradas)."""

    def test_pedido_acima_de_6x_as_entradas_e_negado_no_passo_3(self):
        d = decidir(valor_solicitado=30050.0)          # 6,01x as entradas de R$ 5.000
        self.assertEqual((d["decisao"], d["passo"]), ("NEGADO", 3))

    def test_pedido_exatamente_6x_as_entradas_segue_para_a_analise_de_valor(self):
        d = decidir(valor_solicitado=30000.0)
        self.assertEqual((d["decisao"], d["passo"]), ("APROVADO", 6))

    def test_pedido_excessivo_nao_vira_aprovacao_com_valor_reduzido(self):
        # a sobra comportaria um valor menor, mas reduzir não tira o risco: nega com valor zero
        d = decidir(valor_solicitado=40000.0, mov_entradas_med=5000.0)
        self.assertEqual((d["decisao"], d["valor_aprovado"]), ("NEGADO", 0.0))


    def test_pedido_e_medido_sobre_as_entradas_mesmo_com_renda_declarada_maior(self):
        # 6,01x as entradas reais de R$ 5.000, mas só 3,3x a renda declarada de R$ 9.000
        d = decidir(valor_solicitado=30050.0, renda_declarada=9000.0, renda_decl_sobre_real=1.8)
        self.assertEqual((d["decisao"], d["passo"]), ("NEGADO", 3))


class TestDividaSobreEntradas(unittest.TestCase):
    """P05: parcelas em outras instituições acima de 35% do que ENTRA na conta (não da renda declarada)."""

    def test_parcelas_fora_acima_de_35_porcento_das_entradas_sao_negadas_no_passo_3(self):
        d = decidir(parcelas_outras_instituicoes=1800.0)    # 36% de R$ 5.000
        self.assertEqual((d["decisao"], d["passo"]), ("NEGADO", 3))

    def test_parcelas_fora_em_35_porcento_das_entradas_seguem_para_a_analise_de_valor(self):
        d = decidir(parcelas_outras_instituicoes=1750.0)    # exatamente 35%
        self.assertEqual((d["decisao"], d["passo"]), ("APROVADO", 6))

    def test_a_medida_e_sobre_as_entradas_mesmo_com_renda_declarada_maior(self):
        # 22,5% da renda declarada de R$ 8.000, mas 36% das entradas reais de R$ 5.000
        d = decidir(parcelas_outras_instituicoes=1800.0, renda_declarada=8000.0, renda_decl_sobre_real=1.6)
        self.assertEqual((d["decisao"], d["passo"]), ("NEGADO", 3))

    def test_divida_alta_so_contra_a_renda_declarada_nao_nega(self):
        # 42,5% da renda declarada de R$ 4.000, mas 34% das entradas reais de R$ 5.000
        d = decidir(parcelas_outras_instituicoes=1700.0, renda_declarada=4000.0, renda_decl_sobre_real=0.8)
        self.assertEqual((d["decisao"], d["passo"]), ("APROVADO", 6))


class TestSemMovimentacao(unittest.TestCase):
    def test_entradas_zeradas_nao_quebram_a_politica_e_negam(self):
        d = decidir(mov_entradas_med=0.0, mov_entradas_ult3=0.0, mov_saidas_med=0.0,
                    mov_saidas_sobre_entradas=np.nan, renda_decl_sobre_real=np.nan)
        self.assertEqual(d["decisao"], "NEGADO")


if __name__ == "__main__":
    unittest.main()
