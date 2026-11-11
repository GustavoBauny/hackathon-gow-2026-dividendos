# Changelog

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
