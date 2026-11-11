# Roteiro do pitch · Time Dividendos

São 5 minutos de apresentação e 2 de perguntas. Deixe o painel aberto (`output/painel.html` ou o link publicado) e um terminal na pasta `solucao/`.

## 0:00 · O problema e o resultado (30 s)

A política atual nega quem pagaria e aprova quem não consegue pagar. Nos 2.000 pedidos novos, a nossa:

- aprova **1.510** clientes, contra 1.145 da atual;
- empresta **R$ 10,2 mi**, contra R$ 8,9 mi;
- dá um ganho esperado de **+R$ 662 mil** sobre a atual.

*Mostrar:* os quadros do Resumo.

## 0:30 · Onde a IA entra (60 s)

1. **O alvo vem primeiro.** 6.033 contratos foram aprovados, e boa parte ainda está em andamento.
   - Contar "em dia há 1 mês" como bom pagador dá 10,4% de inadimplência. A real é **16,7%**.
   - A IA aprende por parcela observada. É um modelo de sobrevivência, então contrato novo não conta como bom pagador.
   - Calote é parcela não paga há mais de 60 dias. Nenhum atraso pago passou disso.
2. **Descoberta.** Árvores de decisão varrem todas as variáveis e combinações e devolvem os cortes da Parte 1.
3. **Decisão.** 5 modelos estimam a chance de calote de cada pedido para cada valor possível. A política escolhe o valor com o maior resultado esperado.
4. **O analista decide.** Todo corte é um parâmetro visível.

*Mostrar:* a seção "Onde a IA entra e onde o analista decide".

## 1:30 · Os padrões (75 s)

- **Manchete: o tamanho da parcela.** Com parcela acima de 50% da sobra mensal (entradas menos saídas), **99%** não pagam. O problema não é o cliente, é a parcela, e reduzir o valor resolve.
- **A política atual erra porque olha a renda declarada.** Quem ela reduziu para caber em 30% da renda declarada deu 58% de calote, porque a renda declarada costuma ser maior que a real.
- **Sinais de alerta na movimentação da conta, que o manual disse que passavam despercebidos:**
  - cheque especial em 2 ou mais meses: 82% de calote;
  - gasto acima de 80% das entradas: 98%;
  - renda declarada maior que 2x a real: 92%;
  - pico de entradas nos 3 meses antes do pedido: 33%.
- **Bons pagadores que a atual nega:**
  - score de 450 a 600 sem alertas: 13%;
  - 1 restrição sem alertas: 3%;
  - renda até R$ 2.000 sem alertas: 12%.
  - Score alto não protege: acima de 800 paga igual à média.
- **Medição direta com o piloto:** aprovados no piloto que a atual negaria, sem alerta, deram 11% de calote.

*Mostrar:* a Parte 1, rolando pelos cards e pela tabela "Onde a política atual erra".

## 2:45 · A política e o ganho (60 s)

Os 6 passos, cada um com quantos pedidos decidiu:

1. Bureau.
2. Faixas sem histórico, com 2+ restrições: 174.
3. Sinais de alerta: 166.
4. Teto de parcela: 40% da sobra e 30% das entradas reais.
5. Valor ótimo pelo resultado esperado: 120 negados.
6. Aprovação: 1.510, dos quais 226 com valor reduzido.

O ganho vem de três frentes:

| Frente | Pedidos | Ganho esperado |
|---|---|---|
| Reduzir valor | 129 | +R$ 340 mil |
| Negar quem a atual aprova | 112 | +R$ 165 mil |
| Aprovar quem a atual nega | 477 | +R$ 157 mil |

*Mostrar:* a Parte 2 e a tabela de comparação.

## 3:45 · Demo ao vivo (45 s)

Na seção "Consultar pedido" do painel, ou no terminal com `python explicar.py P-00808`:

| Pedido | O que mostra |
|---|---|
| `P-00808` | Pediu R$ 19.500. A atual daria R$ 12.172; nós aprovamos R$ 6.800, porque a parcela não cabia na sobra. |
| `P-00176` | Score ≤ 600. A atual nega; nós aprovamos o valor cheio. |
| `P-00150` | 1 restrição. A atual nega; nós aprovamos. |
| `P-03661` | A atual aprova; nós negamos por pico de entradas antes do pedido. |
| `P-01208` | A atual aprova; nós negamos porque o risco de 19% passa do limite em que emprestar dá lucro. |

## 4:30 · Validação e o que mudou (30 s)

- **Fora do tempo:** treinado até setembro de 2025, o modelo previu os calotes do piloto, que nunca viu, com AUC de 0,88.
- **Backtest cross-fitted em 10 mil pedidos:** ganho de +R$ 3,49 mi sobre a atual.
- **Réplica da política atual:** reproduz 100% das 8.737 decisões históricas.
- **Bureau:** 126 respostas 503 tratadas com repetição, 0 falhas.
- **Depois do checkpoint:** *(preencher com a v3 do CHANGELOG)*.

## Perguntas prováveis

**Por que negar 2+ restrições, se 1 restrição paga bem?**
Ninguém com 2+ foi aprovado no histórico, então não há desfecho para medir. Aprovar os 123 sem alerta renderia cerca de +R$ 79 mil se eles se comportarem como os de 1 restrição, e cerca de −R$ 169 mil se forem ruins. A recomendação é um piloto controlado, e a decisão é do analista.

**Reduzir o valor não espanta o cliente?**
Para quem a parcela não cabe na sobra, a alternativa é calote: 99% acima de 50% da sobra. Com valor menor, ele vira pagador. Quando dois valores rendem quase igual, ficamos com o maior.

**Como saber que não é overfitting?**
- Validação fora do tempo.
- Backtest em que cada pedido é decidido por um modelo que não o viu.
- Calibração fora da amostra.
- Ensemble de 5 sementes: só 9 a 14 decisões mudam entre ensembles.

**Por que o score quase não importa?**
Sem sinais de alerta, score de 450 a 600 dá 13% e acima de 800 dá 10%. O que separa bom e mau pagador é a movimentação da conta.

**Usaram gênero ou CEP?**
Não. Também ficaram de fora idade e estado civil.

**E se o bureau cair?**
- Timeout em cada chamada.
- Repetição com espera crescente.
- Novas rodadas para quem continuou falhando.
- Cache local.
- Quem ficar sem dados é negado e registrado para reanálise.

Tudo isso é coberto por testes com a API simulada.
