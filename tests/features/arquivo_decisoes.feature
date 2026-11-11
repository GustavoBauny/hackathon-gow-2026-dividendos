# language: pt
Funcionalidade: Arquivo de decisões no formato da organização
  O arquivo dividendos_final.csv é pontuado de forma automática. Fora do formato, ele não é pontuado.
  O pipeline só publica um arquivo que passou na mesma conferência que a organização faz,
  e nunca troca um arquivo bom por um ruim.

  Contexto:
    Dado os pedidos novos
      | id_pedido | valor_solicitado |
      | P-00001   | 10000.00         |
      | P-00002   | 5000.00          |
      | P-00003   | 40000.00         |

  Cenário: Decisões válidas viram o arquivo oficial, ordenado e com duas casas
    Dado as decisões
      | id_pedido | decisao  | valor_aprovado |
      | P-00003   | APROVADO | 30000          |
      | P-00001   | APROVADO | 8500.5         |
      | P-00002   | NEGADO   | 0              |
    Quando o pipeline publica o arquivo
    Então a publicação é aceita
    E o arquivo oficial é exatamente
      """
      id_pedido,decisao,valor_aprovado
      P-00001,APROVADO,8500.50
      P-00002,NEGADO,0.00
      P-00003,APROVADO,30000.00
      """

  Cenário: Decisões com problema não sobrescrevem o último arquivo bom
    Dado um arquivo oficial anterior com o conteúdo "versão boa anterior"
    E as decisões
      | id_pedido | decisao  | valor_aprovado |
      | P-00001   | APROVADO | 12000          |
      | P-00002   | NEGADO   | 0              |
      | P-00003   | APROVADO | 30000          |
    Quando o pipeline publica o arquivo
    Então a publicação é recusada com o problema "acima do solicitado"
    E o arquivo oficial continua com o conteúdo "versão boa anterior"

  Esquema do Cenário: A conferência pega cada tipo de erro de formato
    Dado um arquivo com o conteúdo "<conteudo>"
    Quando o arquivo é conferido
    Então a conferência aponta o problema "<problema>"

    Exemplos:
      | conteudo                                                                                                   | problema               |
      | id_pedido,decisao,valor_aprovado\nP-00001,APROVADO,8500.00\nP-00002,NEGADO,0.00\n                          | ausentes               |
      | id_pedido,decisao,valor_aprovado\nP-00001,APROVADO,8500.00\nP-00001,NEGADO,0.00\nP-00002,NEGADO,0.00\nP-00003,NEGADO,0.00\n | repetido |
      | id_pedido,decisao,valor_aprovado\nP-00001,aprovado,8500.00\nP-00002,NEGADO,0.00\nP-00003,NEGADO,0.00\n     | decisao inválida       |
      | id_pedido,decisao,valor_aprovado\nP-00001,APROVADO,8500.5\nP-00002,NEGADO,0.00\nP-00003,NEGADO,0.00\n      | fora do formato        |
      | id_pedido,decisao,valor_aprovado\nP-00001,APROVADO,400.00\nP-00002,NEGADO,0.00\nP-00003,NEGADO,0.00\n      | abaixo de R$ 500       |
      | id_pedido,decisao,valor_aprovado\nP-00001,NEGADO,0.00\nP-00002,NEGADO,0.00\nP-00003,APROVADO,30000.01\n    | acima de R$ 30.000     |
      | id_pedido,decisao,valor_aprovado\nP-00001,NEGADO,10.00\nP-00002,NEGADO,0.00\nP-00003,NEGADO,0.00\n         | negado com valor       |
      | id_pedido;decisao;valor_aprovado\nP-00001;NEGADO;0.00\nP-00002;NEGADO;0.00\nP-00003;NEGADO;0.00\n          | cabeçalho              |
      | id_pedido,decisao,valor_aprovado\r\nP-00001,NEGADO,0.00\r\nP-00002,NEGADO,0.00\r\nP-00003,NEGADO,0.00\r\n  | CRLF                   |
      | ﻿id_pedido,decisao,valor_aprovado\nP-00001,NEGADO,0.00\nP-00002,NEGADO,0.00\nP-00003,NEGADO,0.00\n    | BOM                    |
      | id_pedido,decisao,valor_aprovado\nP-00001,NEGADO,0.00\nP-00002,NEGADO,0.00\nP-00003,NEGADO,0.00\nP-99999,NEGADO,0.00\n | não está na base |
