"""Testes do cliente do bureau com a API simulada (sem rede).  Rodar: python -m unittest discover tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from bureau_client import BureauClient, TokenInvalido  # noqa: E402

OK = {"id_cliente": "C-1", "score": 700, "restricoes_ativas": 0, "parcelas_outras_instituicoes": 0.0,
      "consultas_90_dias": 1, "meses_historico_bureau": 50}


def resp(status, payload=None, text=""):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = payload
    r.text = text or json.dumps(payload or {})
    return r


class TestBureauClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "cache.jsonl"
        self.cli = BureauClient(token="x", cache_path=self.cache, backoff_base=0.001, backoff_max=0.002, max_tentativas=5)

    def tearDown(self):
        self.tmp.cleanup()

    def _com_respostas(self, *respostas):
        s = mock.Mock()
        s.get.side_effect = list(respostas)
        self.cli._local.s = s
        return s

    def test_repete_em_503_e_timeout_ate_dar_certo(self):
        s = self._com_respostas(resp(503), requests.Timeout("lento"), resp(503), resp(200, OK))
        r = self.cli.consultar("C-1")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["tentativas"], 4)
        self.assertEqual(s.get.call_count, 4)
        self.assertEqual(self.cli.stats.status_503, 2)
        self.assertEqual(self.cli.stats.timeouts, 1)

    def test_payload_corrompido_conta_como_falha_e_repete(self):
        self._com_respostas(resp(200, {"id_cliente": "C-1"}), resp(200, OK))
        self.assertEqual(self.cli.consultar("C-1")["score"], 700)

    def test_401_aborta_sem_repetir(self):
        s = self._com_respostas(resp(401, {"erro": "token"}))
        with self.assertRaises(TokenInvalido):
            self.cli.consultar("C-1")
        self.assertEqual(s.get.call_count, 1)

    def test_404_registra_sem_dados(self):
        self.assertEqual(self._com_respostas(resp(404, {"erro": "x"})) and self.cli.consultar("C-1")["status"], "nao_encontrado")

    def test_desiste_depois_do_maximo_e_nao_grava_no_cache(self):
        self._com_respostas(*[resp(503)] * 5)
        r = self.cli.consultar("C-1")
        self.assertEqual(r["status"], "indisponivel")
        self.assertFalse(self.cache.exists() and "C-1" in self.cache.read_text())

    def test_cache_evita_nova_chamada(self):
        self._com_respostas(resp(200, OK))
        self.cli.consultar("C-1")
        novo = BureauClient(token="x", cache_path=self.cache)
        s = mock.Mock()
        novo._local.s = s
        self.assertEqual(novo.consultar("C-1")["score"], 700)
        s.get.assert_not_called()

    def test_lote_faz_nova_rodada_para_quem_falhou(self):
        chamadas = {"n": 0}

        def get(url, timeout):
            chamadas["n"] += 1
            return resp(503) if chamadas["n"] <= 5 else resp(200, OK)

        s = mock.Mock()
        s.get.side_effect = get
        self.cli.workers = 1
        self.cli._sessao = lambda: s
        with mock.patch("bureau_client.time.sleep"):
            r = self.cli.consultar_lote(["C-1"], rodadas=2)
        self.assertEqual(r[0]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
