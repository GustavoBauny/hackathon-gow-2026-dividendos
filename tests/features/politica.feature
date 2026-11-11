# language: pt
Funcionalidade: Política de crédito proposta
  Cada pedido passa pelos passos na ordem: bureau, faixa com evidência, sinais de alerta,
  capacidade de pagamento e risco x retorno. O primeiro passo que nega encerra a análise.
  O cliente de referência é um assalariado com conta estável: entradas de R$ 5.000 e saídas de
  R$ 3.000 por mês (sobra de R$ 2.000), renda declarada de R$ 5.000, score 780, sem restrição,
  sem dívidas em outras instituições, pedindo R$ 6.000 em 12 parcelas.

  Esquema do Cenário: Sinais de alerta e faixas sem evidência negam o pedido
    Dado um pedido do cliente de referência com <campo> igual a <valor>
    Quando a política proposta é aplicada
    Então o pedido é <decisao> no passo <passo>

    Exemplos: faixa com evidência (o histórico só tem pagamento dentro dela)
      | campo                       | valor  | decisao  | passo |
      | restricoes_ativas           | 1      | APROVADO | 6     |
      | restricoes_ativas           | 2      | NEGADO   | 2     |
      | score                       | 520    | APROVADO | 6     |
      | score                       | 449    | NEGADO   | 2     |
      | renda_declarada             | 1800   | APROVADO | 6     |
      | renda_declarada             | 1500   | NEGADO   | 2     |

    Exemplos: sinais de alerta descobertos no histórico
      | campo                       | valor  | decisao  | passo |
      | mov_saidas_sobre_entradas   | 0.89   | APROVADO | 6     |
      | mov_saidas_sobre_entradas   | 0.90   | NEGADO   | 3     |
      | renda_decl_sobre_real       | 2.0    | APROVADO | 6     |
      | renda_decl_sobre_real       | 2.01   | NEGADO   | 3     |
      | pedido_sobre_entradas       | 6.0    | APROVADO | 6     |
      | pedido_sobre_entradas       | 6.01   | NEGADO   | 3     |
      | outras_sobre_entradas       | 0.35   | APROVADO | 6     |
      | outras_sobre_entradas       | 0.36   | NEGADO   | 3     |
      | mov_entradas_cv             | 0.35   | APROVADO | 6     |
      | mov_entradas_cv             | 0.36   | NEGADO   | 3     |

  Cenário: Cliente com uma única movimentação mensal não é negado por falta de variação
    Dado um pedido do cliente de referência com mov_entradas_cv vazio
    Quando a política proposta é aplicada
    Então o pedido é APROVADO no passo 6

  Cenário: Parcela que não cabe em 45% da sobra é aprovada com valor reduzido
    Dado um pedido do cliente de referência de R$ 15.000 em 12 parcelas
    Quando a política proposta é aplicada
    Então o pedido é APROVADO com R$ 8.958,60
    E a parcela aprovada não passa de 45% da sobra mensal

  Cenário: Conta sem sobra não recebe crédito
    Dado um pedido do cliente de referência com saídas iguais às entradas
    Quando a política proposta é aplicada
    Então o pedido é NEGADO

  Cenário: Analista desliga um sinal de alerta e o modelo de risco continua protegendo
    Dado um pedido do cliente de referência com mov_saidas_sobre_entradas igual a 0.95
    E o analista desligou a regra "gasta_tudo"
    Quando a política proposta é aplicada
    Então o pedido é NEGADO no passo 5

  Esquema do Cenário: Nenhum ajuste do analista aprova parcela acima de 50% da sobra (calote certo)
    Dado um pedido do cliente de referência de R$ 30.000 em 12 parcelas
    E o analista ajustou o teto da sobra para <teto>
    Quando a política proposta é aplicada
    Então o pedido é APROVADO com parcela de até 50% da sobra mensal

    Exemplos:
      | teto      |
      | 0.60      |
      | desligado |

  Cenário: Valor aprovado nunca passa do pedido nem de R$ 30 mil
    Dado um pedido do cliente de referência de R$ 45.000 em 36 parcelas com entradas de R$ 40.000 e saídas de R$ 10.000
    Quando a política proposta é aplicada
    Então o pedido é APROVADO com R$ 30.000,00
