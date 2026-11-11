"""Mostra, passo a passo, por que um pedido novo foi aprovado ou negado.

Uso: python explicar.py P-00070 [P-00071 ...]   (lê output/decisoes_detalhadas.csv gerado por gerar_decisoes.py)
"""
import sys
from pathlib import Path

import pandas as pd

PASSOS = ["Consulta o bureau", "Faixas com histórico", "Sinais de alerta", "Capacidade de pagamento",
          "Risco e retorno (modelo)", "Aprovação"]


def brl(v):
    return "—" if pd.isna(v) else f"R$ {v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


def explicar(r: pd.Series) -> str:
    sobra = r.mov_entradas_med - r.mov_saidas_med
    linhas = [f"\n{r.id_pedido}: {r.decisao}  valor aprovado {brl(r.valor_aprovado)} de {brl(r.valor_solicitado)} "
              f"em {int(r.prazo_meses)} meses   | política atual: {r.decisao_atual} {brl(r.valor_atual) if r.decisao_atual == 'APROVADO' else ''}"]
    for n, nome in enumerate(PASSOS, 1):
        if n == r.passo and r.decisao == "NEGADO":
            linhas.append(f"  [x] {n}. {nome}: {r.motivo}")
        elif n > r.passo:
            linhas.append(f"  [ ] {n}. {nome} (não avaliado)")
        else:
            extra = f": {r.motivo}" if n == 6 else ""
            linhas.append(f"  [v] {n}. {nome}{extra}")
    linhas.append(f"  score {r.score:.0f} | restrições {r.restricoes_ativas:.0f} | consultas 90d {r.consultas_90_dias:.0f} | "
                  f"vínculo {r.tipo_vinculo}")
    linhas.append(f"  renda declarada {brl(r.renda_declarada)} | entradas médias {brl(r.mov_entradas_med)} | sobra mensal {brl(sobra)}")
    linhas.append(f"  meses no cheque especial {r.mov_meses_cheque:.0f} | saídas/entradas {r.mov_saidas_sobre_entradas:.0%} | "
                  f"renda declarada/entradas {r.renda_decl_sobre_real:.2f}x")
    if pd.notna(r.pd):
        linhas.append(f"  teto pela capacidade {brl(r.valor_teto)} | chance de calote {r.pd:.1%} | chance de atraso {r.p_atraso:.0%} | "
                      f"resultado esperado {brl(r.ev_modelo)}")
    return "\n".join(linhas)


if __name__ == "__main__":
    det = pd.read_csv(Path(__file__).resolve().parent / "output" / "decisoes_detalhadas.csv").set_index("id_pedido", drop=False)
    ids = sys.argv[1:] or det.index[:3].tolist()
    for i in ids:
        i = i.strip().upper()
        print(explicar(det.loc[i]) if i in det.index else f"\n{i}: não está na base de novos pedidos")
