# Fortuna Crédito · Time Dividendos

Hackathon GOW 2026. Nova política de crédito para a Fortuna, construída com IA a partir de cerca de 10 mil pedidos históricos e aplicada aos 2 mil pedidos novos.

## Resultado

| | Política atual (réplica) | Política proposta |
|---|---|---|
| Aprovados (2.000 pedidos novos) | 1.145 | 1.510 (226 com valor reduzido) |
| Valor aprovado | R$ 8,86 mi | R$ 10,16 mi |
| Ganho esperado sobre a atual (modelo) | | **+R$ 662 mil** |
| Backtest cross-fitted nos 10 mil pedidos históricos | −R$ 211 mil | +R$ 3,27 mi (**+R$ 3,49 mi**) |

O ganho vem de três frentes:
- **Reduzir o valor** quando a parcela não cabe na sobra mensal do cliente.
- **Negar** aprovados com sinais de alerta, que deram 77% de calote no histórico.
- **Aprovar** quem a política atual nega sem motivo: score de 450 a 600, renda de até R$ 2.000 ou 1 restrição, desde que sem sinais de alerta. No piloto, esse grupo deu 11% de calote.

A réplica da política atual reproduz 100% das 8.737 decisões que ela tomou no histórico (`tests/test_politica.py`).

## Como a política decide

Os passos são aplicados nesta ordem. O primeiro que nega encerra a análise.

1. **Bureau.** Consulta a API. Se ela continuar indisponível depois de todas as tentativas, o pedido é negado e o caso fica registrado.
2. **Faixas sem histórico.** Nega quando não há dado de pagamento para avaliar o risco:
   - 2 ou mais restrições;
   - score abaixo de 450;
   - renda abaixo de R$ 1.500.
3. **Sinais de alerta.** Padrões que a IA encontrou no histórico, com calote entre 70% e 100%:
   - cheque especial em 2 ou mais meses;
   - saídas acima de 80% das entradas;
   - 8 ou mais consultas ao CPF em 90 dias;
   - renda declarada maior que 2 vezes as entradas reais;
   - pico de entradas: os 3 meses antes do pedido 35% ou mais acima dos meses anteriores (cerca de 33% de calote).
4. **Capacidade de pagamento.** Teto de valor:
   - parcela até 40% da sobra mensal (entradas menos saídas);
   - parcela até 30% das entradas reais, usando a menor entre a média de 12 meses e a de 3 meses;
   - parcela até 30% da renda declarada.
5. **Risco e retorno.** Um ensemble de 5 modelos de sobrevivência por parcela (LightGBM calibrado) estima a chance de calote para cada valor possível. O pipeline escolhe o valor que maximiza o resultado esperado (+15% em dia, +5% com atraso, −60% calote). Se nenhum valor dá resultado positivo, nega.
6. **Aprovação.** Aprova o valor escolhido, que pode ser menor que o pedido.

## Alvo: contratos em andamento

Muitos contratos do histórico ainda não terminaram. Um contrato "em dia há 1 mês" não prova que o cliente é bom pagador. Por isso o alvo foi montado assim:

- **Quando é calote.** No histórico, nenhuma parcela paga com atraso passou de 60 dias. Então parcela vencida e não paga há mais de 60 dias conta como calote.
- **Quando o calote começa.** A primeira parcela não paga cai entre a 1ª parcela e cerca de 60% do prazo.
- **Como o modelo aprende.** Cada contrato contribui com uma linha por parcela já observável. É um modelo de hazard em tempo discreto. A chance de calote no contrato inteiro é 1 − ∏(1 − h_k).
- **Taxas do painel.** São calculadas por Kaplan-Meier em tempo relativo, para não subestimar o calote dos contratos recentes.

## Tratamento da API do bureau (`src/bureau_client.py`)

- **Timeout** em cada chamada.
- **Retry com backoff exponencial e jitter** em 503, 5xx, timeout e erro de conexão. Faz até 10 tentativas por cliente e depois novas rodadas para quem continuou falhando.
- **401 aborta a execução.** **404** fica registrado como cliente sem dados.
- **Chamadas em paralelo.** A API não tem limite por minuto.
- **Cache em disco** (`data/bureau_cache.jsonl`). A resposta de um cliente não muda, então reexecutar não chama a API de novo. Se a execução for interrompida, ela continua de onde parou.
- **Validação do payload** e estatísticas de execução: 503, timeouts, latência p50/p95.

## Como rodar

Pré-requisitos: PostgreSQL 16 ou mais novo e Python 3.12 ou mais novo (testado em 3.13).

```bash
# 1. banco
createdb fortuna
pg_restore --no-owner --no-privileges -d fortuna fortuna_hackathon.dump

# 2. dependências
pip install -r requirements.txt

# 3. token do bureau (não versionado)
export FORTUNA_BUREAU_TOKEN=<token do time>   # ou FORTUNA_BUREAU_TOKEN=... em solucao/.env

# 4. conexão com o banco (opcional; padrão: host=localhost dbname=fortuna user=postgres)
export FORTUNA_DSN="host=localhost port=5432 dbname=fortuna user=postgres"

# 5. gerar o arquivo de decisões do zero (cerca de 2 min; a API é consultada uma vez e fica em cache)
python gerar_decisoes.py              # -> output/dividendos_final.csv (validado) + output/painel.html

# opcionais
python avaliar_historico.py           # validação fora do tempo + backtest (cerca de 3 min) -> output/avaliacao.json
python gerar_painel.py                # só regera o painel
python explicar.py P-00070 P-01208    # explica a decisão de pedidos específicos (demo)
python gerar_decisoes.py --so-cache   # roda sem chamar a API (usa só o cache)
python -m unittest discover tests     # testes: falhas do bureau (API simulada) e réplica da política atual
```

Saídas em `output/`:

| Arquivo | Conteúdo |
|---|---|
| `dividendos_final.csv` | Arquivo de entrega: `id_pedido,decisao,valor_aprovado`. É validado contra as regras do manual a cada execução. |
| `painel.html` | Painel para o analista de risco: padrões, política em passos, comparação, validação e consulta de pedido. |
| `decisoes_detalhadas.csv` | Para cada pedido: passo que decidiu, motivo, PD, resultado esperado e decisão da política atual. |
| `resumo.json`, `avaliacao.json` | Números que alimentam o painel. |
| `bureau_execucao_api.json` | Estatísticas da última execução que chamou a API: 503, tentativas e latência. |

## Estrutura

| Caminho | O que faz |
|---|---|
| `src/db.py` | Carrega as tabelas do schema `hackathon` |
| `src/features.py` | Features de bureau, cadastro e 12 meses de movimentação; parcela Price |
| `src/target.py` | Alvo com censura: calote acima de 60 dias e exposição observada |
| `src/modelo.py` | Modelo de hazard por parcela (LightGBM monotônico) e Kaplan-Meier |
| `src/politica.py` | Réplica da política atual e política proposta em passos |
| `src/bureau_client.py` | Cliente resiliente da API do bureau |
| `src/padroes.py` | Descoberta de padrões: varredura por árvore, combinações e onde a política atual erra |
| `gerar_decisoes.py` | Pipeline completo: banco, modelo, bureau, política, CSV e painel |
| `avaliar_historico.py` | Validação fora do tempo e backtest |
| `gerar_painel.py` | Gera `output/painel.html` |
| `explicar.py` | Explica decisões no terminal |

Não usamos gênero, CEP, estado civil nem idade na decisão.
