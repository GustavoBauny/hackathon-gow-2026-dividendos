# language: pt
Funcionalidade: Consulta ao bureau de crédito com falhas de propósito
  A API do bureau falha com 503, demora a responder e pode devolver respostas inesperadas.
  O pipeline precisa conseguir os dados de cada cliente novo sem travar e sem aceitar dado errado.

  Contexto:
    Dado um bureau simulado na rede local
    E um cliente do bureau com timeout curto e no máximo 5 tentativas

  Cenário: Bureau instável responde depois de algumas falhas
    Dado que o bureau responde "503, 503, ok" para o cliente "C-1"
    Quando o pipeline consulta o cliente "C-1"
    Então os dados do cliente "C-1" são aceitos com score 700
    E foram feitas 3 chamadas ao bureau

  Cenário: Bureau lento estoura o timeout e a nova tentativa funciona
    Dado que o bureau responde "lento, ok" para o cliente "C-1"
    Quando o pipeline consulta o cliente "C-1"
    Então os dados do cliente "C-1" são aceitos com score 700
    E a execução registrou 1 timeout

  Esquema do Cenário: Resposta inesperada não é aceita e o pipeline tenta de novo
    Dado que o bureau responde "<resposta>, ok" para o cliente "C-1"
    Quando o pipeline consulta o cliente "C-1"
    Então os dados do cliente "C-1" são aceitos com score 700
    E foram feitas 2 chamadas ao bureau

    Exemplos:
      | resposta          |
      | lista             |
      | nulo              |
      | campo_faltando    |
      | score_texto       |
      | score_fora_faixa  |
      | outro_cliente     |
      | json_quebrado     |

  Cenário: Bureau fora do ar o tempo todo
    Dado que o bureau responde "503, 503, 503, 503, 503" para o cliente "C-1"
    Quando o pipeline consulta o cliente "C-1"
    Então o cliente "C-1" fica sem dados do bureau
    E o cliente "C-1" não vai para o cache

  Esquema do Cenário: Token recusado interrompe a execução sem insistir
    Dado que o bureau responde "<status>" para o cliente "C-1"
    Quando o pipeline consulta o cliente "C-1"
    Então a execução é interrompida por token inválido
    E foram feitas 1 chamadas ao bureau

    Exemplos:
      | status |
      | 401    |
      | 403    |

  Cenário: Pedido malformado não é repetido
    Dado que o bureau responde "400" para o cliente "C-1"
    Quando o pipeline consulta o cliente "C-1"
    Então o cliente "C-1" fica sem dados do bureau
    E foram feitas 1 chamadas ao bureau

  Cenário: Cliente que não é pedido novo
    Dado que o bureau responde "404" para o cliente "C-9"
    Quando o pipeline consulta o cliente "C-9"
    Então o cliente "C-9" é registrado como não encontrado

  Cenário: Token recusado num lote para a fila inteira
    Dado que o bureau responde sempre "401"
    Quando o pipeline consulta um lote de 60 clientes
    Então a execução é interrompida por token inválido
    E foram feitas menos de 60 chamadas ao bureau

  Cenário: Reexecução usa o cache e não chama o bureau
    Dado que o bureau responde "ok" para o cliente "C-1"
    E o pipeline já consultou o cliente "C-1"
    Quando uma nova execução sem token consulta o cliente "C-1"
    Então os dados do cliente "C-1" são aceitos com score 700
    E foram feitas 1 chamadas ao bureau

  Cenário: Execução interrompida deixa uma linha incompleta no cache
    Dado um cache com o cliente "C-1" e uma última linha cortada no meio
    Quando uma nova execução sem token consulta o cliente "C-1"
    Então os dados do cliente "C-1" são aceitos com score 700
    E foram feitas 0 chamadas ao bureau
