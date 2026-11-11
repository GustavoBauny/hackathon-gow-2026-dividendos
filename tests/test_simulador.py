"""Simulador do painel: regras desligáveis, parâmetros aprovados e o motor em JavaScript.

Rodar: python -m unittest discover tests
- As regras desligadas e a leitura do JSON aprovado não precisam do banco.
- O teste do motor JavaScript precisa do Node e de uma execução do pipeline (output/simulador.json);
  sem eles, é pulado.
"""
import json
import shutil
import subprocess
import sys
import unittest
from dataclasses import fields
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))
from politica import Parametros, parametros_de_json, politica_nova  # noqa: E402
from test_politica_v3 import ModeloRiscoFixo, TAXA_ATRASO, pedido  # noqa: E402


def decidir(params: Parametros, **mudancas):
    return politica_nova(pedido(**mudancas), ModeloRiscoFixo(), TAXA_ATRASO, params).iloc[0]


class TestRegraDesligada(unittest.TestCase):
    """O analista pode desligar uma regra no simulador; o pipeline precisa respeitar isso."""

    def test_pedido_excessivo_ligado_nega(self):
        d = decidir(Parametros(), valor_solicitado=30050.0)
        self.assertEqual((d["decisao"], d["passo"]), ("NEGADO", 3))

    def test_pedido_excessivo_desligado_segue_para_o_valor(self):
        d = decidir(Parametros(pedido_sobre_entradas_max=None), valor_solicitado=30050.0)
        self.assertEqual(d["decisao"], "APROVADO")

    def test_restricoes_desligada_aceita_2_restricoes(self):
        self.assertEqual(decidir(Parametros(), restricoes_ativas=2)["passo"], 2)
        self.assertEqual(decidir(Parametros(restricoes_max=None), restricoes_ativas=2)["decisao"], "APROVADO")

    def test_motivo_acompanha_o_corte(self):
        d = decidir(Parametros(meses_cheque_max=2), mov_meses_cheque=3)
        self.assertEqual(d["motivo"], "usou cheque especial em 3+ meses no último ano")


class TestParametrosAprovados(unittest.TestCase):
    def test_le_o_arquivo_exportado_pelo_painel(self):
        arquivo = {"aprovado_por": "Analista", "parametros": {"pedido_sobre_entradas_max": None, "teto_parcela_sobre_sobra": 0.45}}
        p = parametros_de_json(arquivo)
        self.assertIsNone(p.pedido_sobre_entradas_max)
        self.assertEqual(p.teto_parcela_sobre_sobra, 0.45)
        self.assertEqual(p.score_min, Parametros().score_min)

    def test_parametro_desconhecido_e_erro(self):
        with self.assertRaises(ValueError):
            parametros_de_json({"parametros": {"teto_sobra": 0.5}})

    def test_padrao_do_painel_tem_todos_os_parametros(self):
        caminho = RAIZ / "output" / "simulador.json"
        if not caminho.exists():
            self.skipTest("rode o pipeline para gerar output/simulador.json")
        padrao = json.loads(caminho.read_text(encoding="utf-8"))["parametros_padrao"]
        self.assertEqual(set(padrao), {f.name for f in fields(Parametros)})


class TestMotorJavaScript(unittest.TestCase):
    """Com os cortes padrão, o simulador do painel reproduz o arquivo de decisões pedido a pedido."""

    def test_reproduz_o_arquivo_de_decisoes(self):
        node = shutil.which("node")
        sim, csv = RAIZ / "output" / "simulador.json", RAIZ / "output" / "dividendos_final.csv"
        if not node or not sim.exists() or not csv.exists():
            self.skipTest("precisa do Node e de output/simulador.json + output/dividendos_final.csv")
        script = """
const fs = require("fs");
const [motor, simPath, csvPath] = process.argv.slice(1);
const S = require(motor), D = JSON.parse(fs.readFileSync(simPath, "utf8"));
const linhas = fs.readFileSync(csvPath, "utf8").trim().split("\\n").slice(1).map(l => l.split(","));
const grade = S.decodificarGrade(D.grade_pd_u16_b64), P = { ...D.parametros_padrao };
const saida = {};
for (const forcar of [false, true]) {
  const res = S.simular(D, grade, P, { forcarCalculo: forcar });
  let dec = 0, val = 0;
  res.forEach((r, i) => {
    const [id, d, v] = linhas[i];
    if (id !== D.pedidos.id[i]) throw new Error("ordem dos pedidos");
    if ((r.aprova ? "APROVADO" : "NEGADO") !== d) dec++;
    else if (Math.abs(r.valor - Number(v)) > 0.005) val++;
  });
  saida[forcar ? "grade" : "exato"] = { dec, val, aprovados: S.resumir(D, res, P).aprovados };
}
console.log(JSON.stringify(saida));
"""
        out = subprocess.run([node, "-e", script, str(RAIZ / "src" / "simulador.js"), str(sim), str(csv)],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        r = json.loads(out.stdout)
        self.assertEqual((r["exato"]["dec"], r["exato"]["val"]), (0, 0))
        # recalculando o passo 5 pela grade de valores (o que acontece quando o analista muda um teto),
        # a aproximação pode mudar no máximo uns poucos valores, nunca uma decisão
        self.assertEqual(r["grade"]["dec"], 0)
        self.assertLessEqual(r["grade"]["val"], 5)


if __name__ == "__main__":
    unittest.main()
