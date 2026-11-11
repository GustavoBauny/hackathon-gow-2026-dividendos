"""Pipeline: resumo da consulta ao bureau mostrado no painel."""
from gerar_decisoes import resumo_tentativas


def test_resumo_conta_quem_precisou_de_nova_tentativa_na_consulta_original():
    # registros como ficam no cache: 'tentativas' é a tentativa em que a resposta válida chegou
    regs = [{"id_cliente": "C-1", "status": "ok", "tentativas": 1},
            {"id_cliente": "C-2", "status": "ok", "tentativas": 3},
            {"id_cliente": "C-3", "status": "ok", "tentativas": 2},
            {"id_cliente": "C-4", "status": "ok", "tentativas": 1},
            {"id_cliente": "C-5", "status": "indisponivel"}]
    r = resumo_tentativas(regs)
    assert r == {"tentativas_por_cliente": {1: 2, 2: 1, 3: 1}, "clientes_com_retry": 2, "tentativas_max": 3}
