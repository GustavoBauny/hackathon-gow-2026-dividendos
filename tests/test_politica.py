"""A réplica da política atual reproduz as decisões que ela tomou no histórico (precisa do banco restaurado)."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class TestReplicaPoliticaAtual(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from db import carregar
            from features import montar_base
            d = carregar()
        except Exception as e:  # banco indisponível: pula
            raise unittest.SkipTest(f"banco indisponível: {e}")
        base = montar_base(d)
        cls.h = base[(base["tipo_base"] == "historico") & (base["politica_aplicada"] == "atual")].reset_index(drop=True)

    def test_mesma_decisao_em_todos_os_pedidos(self):
        from politica import politica_atual
        r = politica_atual(self.h)
        esperado = np.where(self.h["decisao"] == "aprovado", "APROVADO", "NEGADO")
        self.assertEqual(int((r["decisao"].values != esperado).sum()), 0)

    def test_mesmo_valor_aprovado_ate_centavos(self):
        from politica import politica_atual
        r = politica_atual(self.h)
        ap = self.h["decisao"] == "aprovado"
        dif = np.abs(r.loc[ap, "valor_aprovado"].values - self.h.loc[ap, "valor_aprovado"].values)
        self.assertLess(dif.max(), 1.0)  # arredondamento da parcela: diferença de centavos


if __name__ == "__main__":
    unittest.main()
