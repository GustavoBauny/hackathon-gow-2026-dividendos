# Fortuna Crédito · Time Dividendos

Hackathon GOW 2026. Nova política de crédito para a Fortuna. A IA encontrou os padrões nos 10 mil pedidos históricos e propôs a política. O analista de risco revisa e aprova no painel. A política aprovada é aplicada aos 2 mil pedidos novos.

| Nos 2.000 pedidos novos | Política atual | Nova política |
|---|---|---|
| Pedidos aprovados | 1.145 | 1.287 |
| Valor aprovado | R$ 8,86 mi | R$ 9,04 mi |
| Chance de calote dos aprovados (ponderada por valor) | ~18% | ~8% |
| Resultado esperado (+15% em dia, +5% atraso, −60% calote) | −R$ 31 mil | +R$ 611 mil |

O resultado esperado vem do modelo de risco treinado no histórico (`data/resumo_execucao.json`).

## Como rodar

Pré-requisitos: PostgreSQL 16 ou mais novo (ou Docker) e Python 3.11 ou mais novo.

```bash
# 1. banco (com Docker, se não tiver Postgres local)
docker run -d --name fortuna-pg -e POSTGRES_HOST_AUTH_METHOD=trust -p 5432:5432 \
  -v "$PWD/<pasta do material>":/dump:ro postgres:16-alpine
docker exec fortuna-pg createdb -U postgres fortuna
docker exec fortuna-pg pg_restore --no-owner --no-privileges -U postgres -d fortuna /dump/fortuna_hackathon.dump
#    (sem Docker: createdb fortuna && pg_restore --no-owner --no-privileges -d fortuna fortuna_hackathon.dump)

# 2. dependências
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3. token do bureau (não versionado): qualquer um destes
export FORTUNA_BUREAU_TOKEN=<token do time>     # ou arquivo .bureau_token, ou linha BUREAU:<token> no .env

# 4. conexão com o banco (opcional; padrão: host=localhost port=5432 dbname=fortuna user=postgres)
export FORTUNA_DSN="host=localhost port=5432 dbname=fortuna user=postgres"

# 5. gerar o arquivo de decisões do zero (cerca de 1 minuto sem cache do bureau, 1 segundo com cache)
.venv/bin/python gerar_decisoes.py              # -> dividendos_final.csv (validado no formato do manual)

# 6. painel de experimentação
.venv/bin/streamlit run painel/app.py
```

`gerar_decisoes.py` grava também os artefatos do painel em `data/`: padrões, modelo, decisões detalhadas e resumo da execução.

## Onde a IA entra

1. **Descoberta dos padrões.**
   - 7 agentes de IA (Claude) analisaram o histórico em paralelo, cada um por um ângulo: bureau, movimentação da conta, cadastro e renda, valor e capacidade, atraso e censura, mineração de regras e auditoria da política atual.
   - Para cada achado, um agente verificador refez as contas do zero e tentou refutá-lo. Ele checou robustez (contratos maduros contra exposição, atual contra piloto), confundidores e o limiar exato.
   - Uma síntese juntou tudo, reconstruiu o mecanismo que gera calote e atraso e propôs a política. O roteiro e o relatório estão em [`descoberta/`](descoberta/).
2. **Decisão.** Um modelo treinado no histórico estima a chance de calote e de atraso de cada pedido (`src/risco.py`) e decide entre aprovar e negar pelo resultado esperado.
3. **O humano decide.** No painel, o analista liga, desliga e ajusta cada regra, vê o efeito no histórico e nos pedidos novos e aprova a versão. O pipeline usa a versão aprovada (`politica_aprovada.json`). Sem aprovação gravada, usa a proposta da IA.

## Como a política decide

Os passos são aplicados nesta ordem. O primeiro que nega encerra a análise.

1. **Bureau.** Consulta a API. Se ela continuar indisponível depois de todas as tentativas, nega e registra.
2. **Fora da faixa com evidência.** Nega o que o histórico nunca aprovou e, portanto, não sabe avaliar:
   - 2 ou mais restrições;
   - score até 450;
   - renda declarada até R$ 1.500.
3. **Sinais de alerta descobertos pela IA.** Nega quando:
   - as saídas da conta chegam a 90% ou mais das entradas;
   - a renda declarada passa de 2 vezes o que entra na conta;
   - o pedido passa de 6 vezes o que entra por mês;
   - as parcelas em outras instituições passam de 35% das entradas;
   - as entradas são instáveis (variação acima de 35%).
4. **Valor pela capacidade.**
   - O valor aprovado é o maior em que a parcela cabe em 45% da sobra mensal (entradas menos saídas) e em 30% da renda declarada, até o valor pedido e R$ 30 mil.
   - O calote é certo acima de 50% da sobra.
   - Se nem R$ 500 cabe, nega.
5. **Risco x retorno.**
   - O risco base é de 7,6%, multiplicado pelos fatores do cliente: pedido excessivo ×4,9, dívida alta ×3,1, entradas instáveis ×2,2, histórico curto no bureau ×1,4, aposentado ×0,7.
   - Nega se o resultado esperado for menor que 1% do valor.
6. **Aprovação** no valor do passo 4.

O que mudou em relação à política atual:
- **Sai o corte de score 600.** O score baixo vem do histórico curto no bureau e não prevê calote.
- **Sai o corte de renda R$ 2.000.**
- **Passa a aceitar 1 restrição.** Ela aumenta o atraso, não o calote.
- **Entra a capacidade real**, medida pela sobra da conta em vez da renda declarada.

Não usamos gênero, CEP, estado civil nem idade na decisão. O CEP tem um efeito regional (padrão P12), mas usá-lo seria discriminatório e quase não muda o resultado.

## Alvo: contratos em andamento

Muitos contratos do histórico ainda não terminaram. Um contrato "em dia há 1 mês" não prova que o cliente é bom pagador.

- **Calote.** Nenhuma parcela paga atrasou mais de 60 dias, então parcela vencida e não paga há mais de 60 dias é calote.
- **Exposição.** O calote começa entre a 1ª parcela e 60% do prazo. A exposição de cada contrato é a fração dessa janela que já passou.
- **Inadimplência.** É calotes / exposição. O modelo de calote é uma regressão de Poisson com log(exposição) como offset, então cada fator vira um multiplicador do risco que o analista lê direto.

## Tratamento da API do bureau (`src/bureau_client.py`)

- **Timeout** em cada chamada.
- **Retry com backoff exponencial e jitter** em 503, 5xx, timeout, erro de conexão e resposta inválida. São até 10 tentativas por cliente, mais rodadas extras para quem continuou falhando.
- **401 aborta a execução.** **404** fica registrado como cliente sem dados.
- **Chamadas em paralelo**, porque a API não tem limite por minuto.
- **Cache em disco** (`data/bureau_cache.jsonl`). A resposta de um cliente não muda, então reexecutar não chama a API de novo, e uma execução interrompida continua de onde parou.
- **Validação do payload** e estatísticas da execução (503, timeouts, latência p50/p95), exibidas no painel.

## Estrutura

| Caminho | O que faz |
|---|---|
| `gerar_decisoes.py` | Pipeline completo: banco → bureau → features → modelo → política → CSV validado + artefatos do painel |
| `painel/app.py` | Painel de experimentação (Streamlit): padrões, política, impacto, consulta de pedido, execução e aprovação |
| `src/db.py` | Carrega as tabelas do schema `hackathon` |
| `src/features.py` | Features de bureau, cadastro e 12 meses de movimentação; parcela Price; limiares dos padrões |
| `src/target.py` | Alvo com censura: calote acima de 60 dias e exposição observada |
| `src/risco.py` | Modelo de risco explicável (Poisson com exposição + logística de atraso) |
| `src/politica.py` | Réplica da política atual (bate 100% com o histórico) e política proposta em passos |
| `src/padroes.py` | Padrões encontrados, recalculados a partir dos dados para o painel |
| `src/validacao.py` | Grava e valida o CSV no formato do manual |
| `src/bureau_client.py` | Cliente resiliente da API do bureau |
| `src/modelo.py` | Alternativa avaliada: modelo de hazard por parcela com LightGBM (não usado na decisão final) |
| `descoberta/` | Roteiro multiagente da descoberta e relatório de síntese da IA |
