# Roteiro do pitch · Time Dividendos

São 5 minutos de apresentação e 2 de perguntas. Deixe o painel aberto (`output/painel.html` ou o link publicado) e um terminal na pasta `solucao/`.

## 0:00 · O problema e o resultado (30 s)

A política atual nega quem pagaria e aprova quem não consegue pagar. Nos 2.000 pedidos novos, a nossa:

- aprova **1.365** clientes, contra 1.145 da atual;
- empresta **R$ 9,2 mi**, contra R$ 8,9 mi;
- dá um ganho esperado de **+R$ 608 mil** sobre a atual.

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
- **A política atual erra porque olha a renda declarada.** Quem ela reduziu para caber em 30% da renda declarada deu 58% de calote: 3 em cada 4 tinham pedido mais de 6x o que entra na conta, e reduzir não tirou o risco.
- **Sinais de alerta na movimentação da conta, que o manual disse que passavam despercebidos:**
  - cheque especial em 2 ou mais meses: 82% de calote;
  - gasto acima de 80% das entradas: 98%;
  - renda declarada maior que 2x a real: 92%;
  - pico de entradas nos 3 meses antes do pedido: 27%;
  - **pedido maior que 6x o que entra por mês: 74%, e 70% mesmo com o valor reduzido.** Por isso a v3 nega em vez de reduzir;
  - parcelas em outros bancos acima de 35% das entradas reais: 32%. Contra a renda declarada, a mesma conta não separa ninguém.
- **Bons pagadores que a atual nega:**
  - score de 450 a 600 sem alertas: 11%;
  - 1 restrição sem alertas: 2%;
  - renda até R$ 2.000 sem alertas: 4%.
  - Score alto não protege: acima de 800 paga igual à média.
- **Medição direta com o piloto:** aprovados no piloto que a atual negaria, sem alerta, deram 8% de calote.

*Mostrar:* a Parte 1, rolando pelos cards e pela tabela "Onde a política atual erra".

## 2:45 · A política e o ganho (60 s)

Os 6 passos, cada um com quantos pedidos decidiu:

1. Bureau.
2. Faixas sem histórico, com 2+ restrições: 174.
3. Sinais de alerta: 360 (90 de pedido excessivo e 104 de dívida alta, as duas regras novas da v3).
4. Teto de parcela: 40% da sobra e 30% das entradas reais.
5. Valor ótimo pelo resultado esperado: 71 negados.
6. Aprovação: 1.365, dos quais 114 com valor reduzido.

O ganho vem de três frentes:

| Frente | Pedidos | Ganho esperado |
|---|---|---|
| Negar quem a atual aprova | 199 | +R$ 407 mil |
| Aprovar quem a atual nega | 419 | +R$ 139 mil |
| Reduzir valor | 63 | +R$ 62 mil |

*Mostrar:* a Parte 2 e a tabela de comparação.

## 3:45 · Demo ao vivo (45 s)

Na seção "Consultar pedido" do painel, ou no terminal com `python explicar.py P-00808`:

| Pedido | O que mostra |
|---|---|
| `P-03111` | Pediu R$ 21.000. A atual daria R$ 13.886. A sobra comporta até R$ 10.276, mas nesse valor o risco seria de 17%; aprovamos R$ 8.100, com risco de 9%. |
| `P-00808` | Pediu R$ 19.500, mais de 6x o que entra por mês. A atual daria R$ 12.172; a v2 aprovava R$ 6.800; a v3 nega, porque reduzir não tira o risco. |
| `P-00176` | Score ≤ 600. A atual nega; nós aprovamos o valor cheio. |
| `P-00150` | 1 restrição. A atual nega; nós aprovamos. |
| `P-03661` | A atual aprova; nós negamos por pico de entradas antes do pedido. |
| `P-01208` | A atual aprova; nós negamos porque o risco de 19% passa do limite em que emprestar dá lucro. |

## 4:30 · Validação e o que mudou (30 s)

- **Fora do tempo:** treinado até setembro de 2025, o modelo previu os calotes do piloto, que nunca viu, com AUC de 0,88.
- **Backtest cross-fitted em 10 mil pedidos:** ganho de +R$ 3,2 mi sobre a atual, pelo modelo e fora da amostra. As duas regras da v3 vieram do desfecho real: o modelo sozinho achava esses grupos lucrativos, mas no histórico eles deram 74% e 32% de calote.
- **Réplica da política atual:** reproduz 100% das 8.737 decisões históricas.
- **Bureau:** 126 respostas 503 tratadas com repetição, 0 falhas.
- **O que mudou na v3:** comparamos a política com uma segunda abordagem do time (regras descobertas por agentes de IA + modelo explicável), julgando as duas por três juízes diferentes. Dela vieram dois sinais de alerta, o pedido excessivo e a dívida sobre as entradas reais. Isso tirou 145 aprovações que o histórico mostra que dariam prejuízo.

## Perguntas prováveis

**Por que negar 2+ restrições, se 1 restrição paga bem?**
Ninguém com 2+ foi aprovado no histórico, então não há desfecho para medir. São 84 pedidos novos assim sem nenhum sinal de alerta. Aprová-los seria uma aposta sem nenhum desfecho histórico para medir. A recomendação é um piloto controlado, e a decisão é do analista.

**Reduzir o valor não espanta o cliente?**
Para quem a parcela não cabe na sobra, a alternativa é calote: 99% acima de 50% da sobra. Com valor menor, ele vira pagador. Quando dois valores rendem quase igual, ficamos com o maior.

**Como saber que não é overfitting?**
- Validação fora do tempo.
- Backtest em que cada pedido é decidido por um modelo que não o viu.
- Calibração fora da amostra.
- Ensemble de 5 sementes: só 9 a 14 decisões mudam entre ensembles.

**Por que o score quase não importa?**
Sem sinais de alerta, score de 450 a 600 dá 11% e acima de 800 dá 8%. O que separa bom e mau pagador é a movimentação da conta.

**Usaram gênero ou CEP?**
Não. Também ficaram de fora idade e estado civil.

**E se o bureau cair?**
- Timeout em cada chamada.
- Repetição com espera crescente.
- Novas rodadas para quem continuou falhando.
- Cache local.
- Quem ficar sem dados é negado e registrado para reanálise.

Tudo isso é coberto por testes com a API simulada.
