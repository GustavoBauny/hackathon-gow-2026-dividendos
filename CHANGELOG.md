# Changelog

## Painel do analista, agentes de IA e Docker (11/11, ~12h)

Nenhuma decisão mudou: o CSV é o mesmo da v3, byte a byte.

- **Simulador no painel.** O analista liga, desliga ou muda o corte de cada regra e vê na hora o efeito nos 2.000 pedidos.
  - Mostra o ganho pelo modelo, o calote que clientes iguais tiveram no histórico e os pedidos que mudam.
  - Avisa quando o modelo e o histórico discordam e quando um pedido aprovado não tem caso parecido no histórico.
  - Com os cortes da proposta, reproduz o arquivo de decisões pedido a pedido.
- **Aprovação do analista.** O painel exporta `parametros_aprovados.json`, com o nome de quem aprovou, e `gerar_decisoes.py --parametros` aplica a versão aprovada.
  - Toda regra dos passos 2 e 3 pode ser desligada com `None`.
  - O texto do motivo acompanha o corte escolhido.
- **Agentes de IA no painel.** Nova seção com os achados dos 7 pares de agentes (um propõe, o outro tenta derrubar).
  - Mostra o que foi confirmado, o que foi derrubado e o efeito de CEP que achamos e decidimos não usar.
  - O relatório completo e o roteiro dos agentes estão em `docs/descoberta_agentes/`.
- **Docker.** `docker compose run --rm solucao` sobe o banco, restaura o dump, roda o pipeline e gera o CSV e o painel. `docker compose up -d painel` serve o painel.
  - Versões exatas em `requirements.txt`.
  - Testado do zero, com e sem o cache do bureau: CSV idêntico byte a byte.
- **Testes:** 26 (eram 18). Os novos cobrem as regras desligadas, a leitura dos parâmetros aprovados e o motor do simulador, que deve reproduzir o CSV.
- Referências a uma pasta `solucao/` que não existe foram corrigidas.

## v3 · pedido excessivo e dívida sobre as entradas como sinais de alerta (11/11, ~10h45)

- **Novo sinal de alerta: pedido excessivo.** Nega o pedido quando o valor pedido passa de 6x o que entra por mês na conta.
  - No histórico, esse grupo deu cerca de 74% de calote. Entre os que a política atual aprovou com o valor reduzido, foram 70%.
  - O modelo da v2 não via o valor pedido, só o concedido, e previa 9% para esses clientes.
  - Na v3 o pedido é negado em vez de reduzido.
- **Novo sinal de alerta: dívida em outros bancos acima de 35% das entradas reais.**
  - Dá cerca de 32% de calote, com degrau nítido em 35% (11% entre 30% e 35%).
  - A mesma medida contra a renda declarada quase não separa bons de maus pagadores.
- **Origem.** Comparativo neutro entre a v2 e a política da branch `pipeline-painel` (regras descobertas por agentes de IA + modelo explicável).
  - Cada política foi julgada pelo próprio modelo, pelo modelo da outra, pelas taxas do histórico sem modelo e por backtest.
  - A v2 com essas duas regras foi a opção mais robusta: pior caso de R$ 586 mil entre os juízes, contra R$ 433 mil da v2.
- **2.000 pedidos novos:** a proposta aprova 1.365 (R$ 9,15 mi), contra 1.145 da atual.
  - 618 decisões diferentes da atual.
  - 145 pedidos que a v2 aprovava passam a ser negados: 86 de pedido excessivo e 59 de dívida alta. Nenhuma outra decisão muda.
  - 114 aprovados com valor reduzido.
  - Ganho esperado pelo modelo: +R$ 608 mil, contra +R$ 662 mil na v2. O número cai porque o modelo da v2 subestima o risco desses dois grupos.
  - Pelas taxas de calote observadas no histórico, o lucro esperado sobe de R$ 459 mil (v2) para R$ 625 mil (v3).
- **Padrões:**
  - dois cards novos;
  - "Dívidas fora acima de 30% da renda" virou "parece risco, mas não é": quando a dívida fica abaixo de 35% das entradas, o calote é menor que o dos clientes sem alerta.
- **Testes:** `tests/test_politica_v3.py` cobre os limites das duas regras, a negativa no lugar da redução e a medida sobre as entradas (no pedido e na dívida). São 9 casos, sem banco.
- **Backtest cross-fitted (resultado esperado pelo modelo, fora da amostra):** ganho de +R$ 3,23 mi, contra +R$ 3,49 mi da v2.
  - A v3 cai nessa métrica porque o juiz é o próprio modelo, que acha lucrativos os dois grupos negados.
  - Pelo desfecho real, esses grupos deram 74% e 32% de calote.
  - A AUC fora do tempo continua em 0,88, porque o modelo não mudou.


## v2 · revisão antes do checkpoint (11/11, ~09h25)

- **Novo padrão: pico de entradas antes do pedido.** Quem tem os 3 meses anteriores 35% ou mais acima da média dos meses anteriores dá cerca de 33% de calote (137 contratos). Passou a ser sinal de alerta no passo 3 e feature do modelo.
- **Novo teto no passo 4:** parcela até 30% das entradas reais, usando a menor entre a média de 12 meses e a de 3 meses. Acima disso, a inadimplência vai a 28%.
- **Ensemble de 5 modelos com sementes diferentes.** Com um modelo só, de 10 a 60 decisões mudavam entre sementes; com o ensemble, de 9 a 14.
- **Empate técnico no valor:** se dois valores dão resultado esperado a até 2% um do outro, a política fica com o maior.
- **Chance de atraso:** ganhou um terceiro segmento, dívidas em outros bancos acima de 30% da renda (39%).
- **Painel:**
  - seção "Parece risco, mas não é", com conta nova e score alto;
  - explicação correta de como a varredura vira corte;
  - réplica da política atual validada.
- **Testes:**
  - cliente do bureau com API simulada (503, timeout, payload inválido, 401, 404, cache e nova rodada);
  - réplica da política atual: 100% das 8.737 decisões históricas.
- **2.000 pedidos novos:** a proposta aprova 1.510 (R$ 10,16 mi), contra 1.145 da atual.
  - 589 decisões diferentes da atual.
  - 226 pedidos aprovados com valor reduzido.
  - Ganho esperado pelo modelo: +R$ 662 mil.
- **Backtest cross-fitted:** ganho de +R$ 3,49 mi, contra +R$ 3,47 mi da v1. AUC fora do tempo subiu de 0,87 para 0,88.

## v1 · pré-checkpoint (11/11, ~09h)

- Alvo com censura: calote = parcela não paga há mais de 60 dias; modelo de hazard por parcela.
- Calibração isotônica sobre Kaplan-Meier, fora da amostra.
- Política em 6 passos: bureau → faixas sem histórico → sinais de alerta → teto pela capacidade → valor ótimo por resultado esperado → aprovação.
- **2.000 pedidos novos:** a proposta aprova 1.533 (R$ 10,31 mi), contra 1.145 (R$ 8,86 mi) da política atual.
  - 574 decisões diferentes da atual.
  - 254 pedidos aprovados com valor reduzido.
  - Ganho esperado pelo modelo: +R$ 666 mil.
- **Backtest cross-fitted em 10 mil pedidos históricos:** −R$ 228 mil na política atual, contra +R$ 3,24 mi na proposta (+R$ 3,47 mi de ganho).
- **Bureau:** 2.126 chamadas, 126 respostas 503 tratadas, no máximo 3 tentativas por cliente e 0 falhas.
