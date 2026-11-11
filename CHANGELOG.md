# Changelog

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
