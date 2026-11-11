# Fortuna Crédito · Time Dividendos

Hackathon GOW 2026. Nova política de crédito para a Fortuna, construída com IA a partir de cerca de 10 mil pedidos históricos e aplicada aos 2 mil pedidos novos.

> **Status:** em construção. O pipeline completo que gera `dividendos_final.csv` (`gerar_decisoes.py`) ainda está sendo escrito. Os módulos em `src/` já funcionam.

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
   - renda declarada maior que 2 vezes as entradas reais.
4. **Capacidade de pagamento.** Teto de valor:
   - parcela até 40% da sobra mensal (entradas menos saídas);
   - parcela até 30% da renda declarada.
5. **Risco e retorno.** Um modelo de sobrevivência por parcela (LightGBM) estima a chance de calote para cada valor possível. O pipeline escolhe o valor que maximiza o resultado esperado (+15% em dia, +5% com atraso, −60% calote). Se nenhum valor dá resultado positivo, nega.
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

Pré-requisitos: PostgreSQL 16 ou mais novo e Python 3.11 ou mais novo.

```bash
# 1. banco
createdb fortuna
pg_restore --no-owner --no-privileges -d fortuna fortuna_hackathon.dump

# 2. dependências
pip install -r requirements.txt

# 3. token do bureau (não versionado)
export FORTUNA_BUREAU_TOKEN=<token do time>   # ou grave em solucao/.bureau_token

# 4. conexão com o banco (opcional; padrão: host=localhost dbname=fortuna user=postgres)
export FORTUNA_DSN="host=localhost port=5432 dbname=fortuna user=postgres"

# 5. gerar o arquivo de decisões (em construção)
python gerar_decisoes.py
```

## Estrutura

| Caminho | O que faz |
|---|---|
| `src/db.py` | Carrega as tabelas do schema `hackathon` |
| `src/features.py` | Features de bureau, cadastro e 12 meses de movimentação; parcela Price |
| `src/target.py` | Alvo com censura: calote acima de 60 dias e exposição observada |
| `src/modelo.py` | Modelo de hazard por parcela (LightGBM monotônico) e Kaplan-Meier |
| `src/politica.py` | Réplica da política atual e política proposta em passos |
| `src/bureau_client.py` | Cliente resiliente da API do bureau |

Não usamos gênero, CEP, estado civil nem idade na decisão.
