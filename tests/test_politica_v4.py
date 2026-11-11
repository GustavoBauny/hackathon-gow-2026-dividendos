"""v4: cheque especial e consultas ao CPF deixaram de negar sozinhos (respostas da Fortuna, 11/11).

Rodar: python -m unittest discover tests   (não precisa do banco)

São marcas de quem gasta mais de 80% do que entra, e a regra das saídas já nega esse cliente.
Os testes usam o mesmo cliente estável e o mesmo modelo dublê (calote de 5%) de test_politica_v3.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from politica import Parametros, politica_nova  # noqa: E402
from test_politica_v3 import ModeloRiscoFixo, TAXA_ATRASO, pedido  # noqa: E402


def decidir(params: Parametros = Parametros(), **mudancas):
    return politica_nova(pedido(**mudancas), ModeloRiscoFixo(), TAXA_ATRASO, params).iloc[0]


class TestChequeEConsultasNaoNegamSozinhos(unittest.TestCase):

    def test_regras_desligadas_na_proposta(self):
        self.assertIsNone(Parametros().meses_cheque_max)
        self.assertIsNone(Parametros().consultas_90d_max)

    def test_cheque_recorrente_sem_gasto_alto_segue_para_o_valor(self):
        d = decidir(mov_meses_cheque=4)
        self.assertEqual((d["decisao"], d["passo"]), ("APROVADO", 6))

    def test_muitas_consultas_sem_gasto_alto_segue_para_o_valor(self):
        d = decidir(consultas_90_dias=12)
        self.assertEqual((d["decisao"], d["passo"]), ("APROVADO", 6))

    def test_com_gasto_acima_de_80_porcento_continua_negado(self):
        # o perfil que o cheque e as consultas marcam: a regra das saídas nega
        d = decidir(mov_meses_cheque=4, consultas_90_dias=12, mov_saidas_sobre_entradas=0.95, mov_saidas_med=4750.0)
        self.assertEqual((d["decisao"], d["passo"]), ("NEGADO", 3))
        self.assertIn("80%", d["motivo"])


class TestAnalistaPodeReligar(unittest.TestCase):
    """No simulador, o analista pode religar as regras com o corte antigo (v3)."""

    def test_cheque_religado_nega_2_ou_mais_meses(self):
        d = decidir(Parametros(meses_cheque_max=1), mov_meses_cheque=2)
        self.assertEqual((d["decisao"], d["passo"]), ("NEGADO", 3))
        self.assertEqual(d["motivo"], "usou cheque especial em 2+ meses no último ano")

    def test_consultas_religadas_negam_8_ou_mais(self):
        d = decidir(Parametros(consultas_90d_max=7), consultas_90_dias=8)
        self.assertEqual((d["decisao"], d["passo"]), ("NEGADO", 3))
        self.assertEqual(d["motivo"], "8+ consultas ao CPF em 90 dias")


class TestSimuladorComRegraDesligadaNaProposta(unittest.TestCase):
    """A evidência do simulador para uma regra que a proposta deixa desligada (padrão None)."""

    @staticmethod
    def historico():
        # 8 contratos sem nenhum outro sinal de alerta; 4 com cheque em 3 meses, 1 deles com calote
        import numpy as np
        import pandas as pd
        return pd.DataFrame([{
            "restricoes_ativas": 0, "score": 700, "renda_declarada": 5000.0, "mov_meses_cheque": 3 if i < 4 else 0,
            "mov_saidas_sobre_entradas": 0.6, "consultas_90_dias": 1, "renda_decl_sobre_real": 1.0, "mov_tendencia_entradas": 1.0,
            "valor_solicitado": 6000.0, "mov_entradas_med": 5000.0, "mov_entradas_ult3": 5000.0, "mov_saidas_med": 3000.0,
            "parcelas_outras_instituicoes": 0.0, "valor_aprovado": 6000.0, "prazo_meses": 12,
            "k_evento": 3.0 if i == 0 else np.nan, "n_observaveis": 12} for i in range(8)])

    def test_regra_desligada_nao_dispara(self):
        from simulador import _dispara
        h = self.historico()
        self.assertFalse(_dispara(h["mov_meses_cheque"], None, "maior").any())

    def test_evidencia_mostra_quem_ligar_a_regra_passaria_a_negar(self):
        from simulador import REGRAS, evidencia
        ev = evidencia(self.historico())["meses_cheque_max"]
        valores = next(r["valores"] for r in REGRAS if r["id"] == "meses_cheque_max")
        self.assertEqual(ev["grupo_padrao"]["n"], 0)                      # desligada: não libera ninguém
        self.assertEqual(ev["faixas"][valores.index(1)]["n"], 4)          # ligar em 2+ meses pega os 4
        self.assertEqual(ev["faixas"][valores.index(3)]["n"], 0)          # ligar em 4+ meses não pega ninguém


if __name__ == "__main__":
    unittest.main()
