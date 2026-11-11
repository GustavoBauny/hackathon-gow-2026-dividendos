# Fortuna Crédito · Time Dividendos

Hackathon GOW 2026. Nova política de crédito para a Fortuna, construída com IA a partir de cerca de 10 mil pedidos históricos e aplicada aos 2 mil pedidos novos.

## Resultado

| | Política atual (réplica) | Política proposta |
|---|---|---|
| Aprovados (2.000 pedidos novos) | 1.145 | 1.365 (114 com valor reduzido) |
| Valor aprovado | R$ 8,86 mi | R$ 9,15 mi |
| Ganho esperado sobre a atual (modelo) | | **+R$ 608 mil** |
| Backtest cross-fitted nos 10 mil pedidos históricos (resultado esperado pelo modelo, fora da amostra) | −R$ 211 mil | +R$ 3,02 mi (**+R$ 3,23 mi**) |

Os dois números de ganho usam o próprio modelo como juiz. O modelo considera lucrativos os pedidos acima de 6x as entradas
e os de dívida acima de 35% das entradas, grupos que a v3 passou a negar. Por isso, nessa métrica, a v3 fica abaixo da v2
(+R$ 3,49 mi no backtest e +R$ 662 mil nos novos). Pelo desfecho real, esses grupos deram cerca de 74% e 32% de calote, e o
lucro esperado pelas taxas observadas no histórico sobe de R$ 459 mil (v2) para R$ 625 mil (v3).

O ganho vem de três frentes:
- **Reduzir o valor** quando a parcela não cabe na sobra mensal do cliente.
- **Negar** aprovados com sinais de alerta, que deram 56% de calote no histórico.
- **Aprovar** quem a política atual nega sem motivo: score de 450 a 600, renda de até R$ 2.000 ou 1 restrição, desde que sem sinais de alerta. No piloto, esse grupo deu 8% de calote.

A réplica da política atual reproduz 100% das 8.737 decisões que ela tomou no histórico (`tests/test_politica.py`).

## Como a política decide

Os passos são aplicados nesta ordem. O primeiro que nega encerra a análise.

1. **Bureau.** Consulta a API. Se ela continuar indisponível depois de todas as tentativas, o pedido é negado e o caso fica registrado.
2. **Faixas sem histórico.** Nega quando não há dado de pagamento para avaliar o risco:
   - 2 ou mais restrições;
   - score abaixo de 450;
   - renda abaixo de R$ 1.500.
3. **Sinais de alerta.** Padrões que a IA encontrou no histórico, com calote bem acima da média de 17% (de cerca de 27% a 100%):
   - cheque especial em 2 ou mais meses;
   - saídas acima de 80% das entradas;
   - 8 ou mais consultas ao CPF em 90 dias;
   - renda declarada maior que 2 vezes as entradas reais;
   - pico de entradas: os 3 meses antes do pedido 35% ou mais acima dos meses anteriores (cerca de 27% de calote);
   - pedido maior que 6 vezes o que entra por mês na conta (cerca de 74% de calote; mesmo com a parcela entre 30% e 50% da sobra, perto de 50%, contra 11% a 19% de quem pede menos: por isso nega em vez de reduzir);
   - parcelas em outros bancos acima de 35% do que entra na conta (cerca de 32% de calote).
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

## Painel e simulador do analista

O painel (`output/painel.html`) é uma página só, que abre no navegador sem servidor. Tem duas partes, como pede o manual: os padrões e a política em passos.

- **Simulador.** O analista liga, desliga ou muda o corte de cada regra dos passos 2 a 5, sem ler código. O painel refaz na hora as decisões dos 2.000 pedidos, com o mesmo modelo do pipeline, e mostra:
  - aprovados, valor e ganho esperado sobre a política atual;
  - o calote que clientes iguais tiveram no histórico, na faixa que a mudança libera ou passa a negar;
  - um aviso quando o modelo e o histórico discordam (exemplo: desligar o pedido excessivo rende +R$ 646 mil pelo modelo, mas +R$ 366 mil se os liberados repetirem o calote do histórico);
  - um aviso para pedidos aprovados sem nenhum caso parecido no histórico;
  - a lista dos pedidos que mudam.
- **Com os cortes da proposta, o simulador reproduz o arquivo de decisões pedido a pedido.** Isso é testado em `tests/test_simulador.py`.
- **Aprovação.** O analista aprova uma versão com o nome dele, e o painel baixa `parametros_aprovados.json`. O pipeline só aplica uma versão aprovada:
  `python gerar_decisoes.py --parametros parametros_aprovados.json`. No Docker, ponha o arquivo em `output/` e passe `--parametros output/parametros_aprovados.json`.
- **Descoberta com agentes de IA.** Além da varredura por árvores, 7 pares de agentes de IA (um propõe padrões, o outro tenta derrubá-los) analisaram o histórico. O resumo está no painel; o relatório completo e o roteiro dos agentes ficam em `docs/descoberta_agentes/`.

## Como rodar

### Com Docker (do zero, um comando)

Pré-requisito: Docker com Compose v2. Não precisa de Python nem de PostgreSQL na máquina.

```bash
# 1. dump do banco na raiz do projeto (ou: export FORTUNA_DUMP=/caminho/fortuna_hackathon.dump)
cp /caminho/fortuna_hackathon.dump .

# 2. token do bureau (não versionado): no ambiente ou num .env na raiz do projeto
echo "FORTUNA_BUREAU_TOKEN=<token do time>" > .env

# 3. gerar o arquivo de decisões do zero
#    sobe o banco, restaura o dump, treina o modelo e consulta a API (cerca de 4 min na primeira vez, com o build)
docker compose run --rm --build solucao     # -> output/dividendos_final.csv (validado) + output/painel.html

# 4. painel do analista
docker compose up -d painel                 # http://localhost:8080/painel.html
```

Opcionais:

```bash
docker compose run --rm solucao python -m unittest discover tests      # testes, inclusive a réplica da política atual no banco
docker compose run --rm solucao python explicar.py P-00808            # explica a decisão de um pedido
docker compose run --rm solucao python gerar_decisoes.py --so-cache   # roda sem chamar a API (usa só o cache)
docker compose run --rm solucao python avaliar_historico.py           # validação fora do tempo + backtest
docker compose down -v                                                # apaga os containers e o banco
```

- O banco fica só na rede interna do Compose, sem porta no host. Não conflita com um PostgreSQL local na 5432.
- O dump é restaurado só na primeira subida. Para restaurar de novo, use `docker compose down -v`.
- `output/` e `data/` são pastas do host montadas no container. O CSV e o painel aparecem em `output/`. O cache do bureau fica em `data/` entre execuções.
- As versões em `requirements.txt` são exatas. Com elas, o CSV sai idêntico byte a byte ao versionado, com ou sem cache do bureau (testado também com 1, 3 e 12 núcleos).

### Sem Docker

Pré-requisitos: PostgreSQL 16 ou mais novo e Python 3.14.

```bash
# 1. banco
createdb fortuna
pg_restore --no-owner --no-privileges -d fortuna fortuna_hackathon.dump

# 2. dependências (versões exatas)
pip install -r requirements.txt

# 3. token do bureau (não versionado)
export FORTUNA_BUREAU_TOKEN=<token do time>   # ou FORTUNA_BUREAU_TOKEN=... no .env da raiz do projeto

# 4. conexão com o banco (opcional; padrão: host=localhost dbname=fortuna user=postgres)
export FORTUNA_DSN="host=localhost port=5432 dbname=fortuna user=postgres"

# 5. gerar o arquivo de decisões do zero (cerca de 2 min; a API é consultada uma vez e fica em cache)
python gerar_decisoes.py              # -> output/dividendos_final.csv (validado) + output/painel.html

# opcionais
python avaliar_historico.py           # validação fora do tempo + backtest (cerca de 3 min) -> output/avaliacao.json
python gerar_painel.py                # só regera o painel
python explicar.py P-00070 P-01208    # explica a decisão de pedidos específicos (demo)
python gerar_decisoes.py --so-cache   # roda sem chamar a API (usa só o cache)
python -m unittest discover tests     # testes: falhas do bureau (API simulada), réplica da política atual, regras da v3 e simulador
python gerar_decisoes.py --parametros parametros_aprovados.json   # aplica a versão aprovada no simulador do painel
```

Saídas em `output/`:

| Arquivo | Conteúdo |
|---|---|
| `dividendos_final.csv` | Arquivo de entrega: `id_pedido,decisao,valor_aprovado`. É validado contra as regras do manual a cada execução. |
| `painel.html` | Painel para o analista de risco: padrões, política em passos, simulador, comparação, validação e consulta de pedido. |
| `simulador.json` | Dados do simulador: medidas de cada pedido, resultado do passo 5 e chance de calote por valor, de R$ 100 em R$ 100. |
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
| `src/simulador.py` | Prepara os dados do simulador do painel e a evidência do histórico para cada corte |
| `src/simulador.js`, `src/simulador_ui.js` | Motor do simulador (refaz a política no navegador) e a tela dele |
| `docs/descoberta_agentes/` | Relatório e roteiro dos agentes de IA que descobriram e testaram padrões |
| `Dockerfile`, `docker-compose.yml`, `docker/` | Execução do zero com Docker: banco restaurado do dump, pipeline e painel |
| `gerar_decisoes.py` | Pipeline completo: banco, modelo, bureau, política, CSV e painel |
| `avaliar_historico.py` | Validação fora do tempo e backtest |
| `gerar_painel.py` | Gera `output/painel.html` |
| `explicar.py` | Explica decisões no terminal |

Não usamos gênero, CEP, estado civil nem idade na decisão.
