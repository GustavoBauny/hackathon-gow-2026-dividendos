# Fortuna Crédito: padrões de inadimplência, regra geradora e política proposta

Esta síntese junta o trabalho de 7 pares de analista e verificador (bureau, movimentação, cadastro e renda, valor e capacidade, atraso e censura, mineração de regras e auditoria da política atual). Nos pontos em que os achados conflitavam, refiz as contas (scripts em `<area-de-trabalho>/agents/synthesis/`).

**Como medimos a inadimplência.** Muitos contratos ainda estão em curso, então a taxa é ajustada por exposição: calotes observados divididos pela soma de `exposicao`. Calote é uma parcela vencida e não paga há mais de 60 dias. O subconjunto maduro serve de checagem. A taxa ingênua de 10,4% subestima o risco: a taxa real dos aprovados é 17,2%, ou 17,6% nos contratos maduros.

**"Afeta N clientes"** conta os pedidos entre os 2.000 novos.

**Equilíbrio do negócio.** O ganho esperado por real emprestado é (1−PD)×(0,15−0,10×L) − 0,60×PD, em que L é a fração de atraso entre os que pagam. Com L = 21,6%, a operação empata quando a inadimplência (PD) é de cerca de 17,6%.

---

## 1. Padrões confirmados, do maior ao menor impacto no lucro

### P01. Parcela acima da metade da sobra da conta (regra que depende do valor aprovado)
Clientes cuja parcela aprovada passa de 50% da sobra mensal da conta, ou que não têm sobra, têm inadimplência de 100%, contra 11% da média. Afeta 231 clientes.

- **Regra:** `sobra = mov_entradas_med − mov_saidas_med` (médias simples dos 12 meses). O calote é certo quando `parcela_Price(valor_APROVADO, prazo) / sobra > 0,50` ou quando `sobra ≤ 0`.
- **Nitidez do degrau:** fica exatamente em 0,50. Contratos maduros: de 0,49 a 0,50 dão 29% (4 de 12), de 0,50 a 0,51 dão 7 de 7, e acima disso 100%.
- **Histórico:** 1.157 pedidos; 348 aprovados, com 238 calotes em 226,9 de exposição e 127 de 127 maduros.
- **Robustez:** vale nas políticas atual e piloto e em todas as faixas de score.
- **O gatilho é o valor aprovado, não o pedido:** quem pediu acima de 0,5 da sobra, mas foi aprovado abaixo, tem 15,8% (6 de 36 maduros).
- **Novos:** 231 pedidos violam a regra no valor pedido (125 fora dos perfis P02 e P04). Todos podem ser recuperados reduzindo o valor.
- **Ação:** limitar o valor a `0,45 × sobra × (1−1,03^−prazo)/0,03`.

### P02. Perfil que gasta tudo o que entra (saídas ≥ 90% das entradas)
Clientes cujas saídas chegam a 90% ou mais das entradas da conta têm inadimplência de 100%, contra 15% da média. Afeta 97 clientes.

- **Regra:** `mov_saidas_sobre_entradas ≥ 0,9`. Não existe nenhum caso entre 0,5 e 0,949 (o grupo vai de 0,949 a cerca de 1,2).
- **Origem do perfil:** é gerado em bloco. Três meses antes do pedido há um mês com saídas de cerca de 7 vezes as entradas, depois uso de cheque especial em 2 a 4 meses e 4 a 10 consultas ao CPF.
- **Histórico:** 490 pedidos; 156 aprovados, com 102 calotes em 94,1 de exposição e 47 de 47 maduros.
- **Relação com P01:** entre os aprovados, o perfil está inteiro dentro da regra P01. A ação é a mesma: negar.

### P03. Renda declarada inflada (maior que 2 vezes as entradas reais)
Clientes que declaram renda maior que 2 vezes o que de fato entra na conta têm inadimplência de 92%, contra 17% da média. Afeta 66 clientes.

- **Regra:** `renda_declarada / mov_entradas_med > 2`. Na prática o grupo fica acima de 3x: 292 dos 304 casos do histórico. Só aparece em contas novas (`mov_meses ≤ 2`).
- **Histórico:** 304 pedidos; 42 aprovados, com 25 calotes em 23,8 de exposição e 8 de 9 maduros (há 1 adimplente maduro).
- **Não é efeito de capacidade:** a parcela/sobra mediana é de 0,14.
- **Não se sobrepõe** ao perfil P02.

### P04. Pedido excessivo (valor pedido maior que 6 vezes as entradas mensais)
Clientes que pedem mais de 6 vezes o que entra por mês na conta têm inadimplência de 50%, contra 10% da média, e reduzir o valor não resolve. Afeta 121 clientes.

- **Regra:** `valor_SOLICITADO / mov_entradas_med > 6`. A distribuição é quase vazia entre 5 e 6.
- **Histórico:** 582 pedidos. Na população limpa, 139 aprovados com 43 calotes em 86,9 de exposição (49,5%) e 26 de 49 maduros.
- **Conflito resolvido nesta síntese:** este achado explica os de "valor reduzido ao teto de 30%" (59%) e de "parcela ≥ 27–30% da renda declarada" (32–35%).
  - Reduzidos ao teto com pedido ≤ 6x as entradas: 12,6% (n=59, 6 de 44 maduros).
  - Não reduzidos com pedido > 6x: 50% (n=11).
  - Entre os reduzidos com pedido > 6x, a razão valor_APROVADO/entradas não muda nada.
  - Poisson com offset de exposição: com a regra de 6x o AIC é 2.107,6. As alternativas dão 2.124,1 (foi reduzido), 2.122,5 (parcela ≥ 27% da renda declarada) e 2.123,0 (parcela pedida > 30%). Com a regra de 6x no modelo, "foi reduzido" fica com p=0,54 e "parcela ≥ 27%" com p=0,12.
- **Novos:** 121 pedidos (106 fora dos perfis P02 e P03).
- **Ação:** negar. Esse grupo dá cerca de −24% por real emprestado.

### P05. Parcelas em outras instituições acima de 35% das entradas reais
Clientes cujas parcelas em outras instituições passam de 35% das entradas mensais da conta têm inadimplência de 29%, contra 10% da média, e atrasam em 46% dos casos, contra 22%. Afeta 165 clientes.

- **Regra:** `parcelas_outras_instituicoes / mov_entradas_med > 0,35`. O denominador é a entrada REAL, não a renda declarada.
- **Degrau:** de 0,34 a 0,35 dá 7%; de 0,35 a 0,36 dá 38%. Acima disso fica num platô de cerca de 28%.
- **Histórico:** 828 pedidos. Na população limpa, 350 aprovados com 62 calotes em 212,2 de exposição (29,2%) e maduros a 31%.
- **A versão com renda declarada é proxy:** dívida > 30% da renda declarada com dívida ≤ 35% das entradas tem calote de só 2,4%.
- **Novos:** 165 pedidos (144 sem outra regra).
- **Ação:** negar. O lucro esperado fica em cerca de −9,5% por real.

### P06. O score do bureau não prevê inadimplência (oportunidade de aprovação)
Clientes com score até 600 e sem outros fatores de risco têm inadimplência de 11%, contra 9% da média dos clientes limpos (diferença não significativa). Afeta 445 clientes, hoje negados.

- **Como o score é gerado:**
  - Se `meses_historico_bureau < 12`, o score segue uma uniforme U(450, 590) (KS p=0,43).
  - Caso contrário, segue uma normal N(768, 100) truncada em 1000.
  - Por isso o corte "score > 600" equivale, na prática, a "histórico ≥ 12 meses".
- **Sem efeito no risco:** de 600 a 1000 a curva é plana. No Poisson, o coeficiente do score é de cerca de 0 (p=0,99).
- **Histórico:** 2.385 pedidos com score ≤ 600. Na população limpa, 221 aprovados com 11,3%, contra 8,6% acima de 600.
- **Novos:** 445 pedidos (384 com histórico curto, menos de 12 meses).
- **Ação:** retirar o corte de score. A política proposta aprova 287 desses clientes.

### P07. Entradas muito instáveis (só autônomos e empresários)
Clientes com entradas mensais muito instáveis (coeficiente de variação > 35%) têm inadimplência de 20%, contra 9% da média. Afeta 269 clientes.

- **Regra:** `mov_entradas_cv > 0,35`. Assalariados (máximo 0,28) e aposentados nunca chegam ao corte.
- **Histórico:** 1.344 pedidos. Na população limpa, 578 aprovados com 20,2% e maduros a 19,6%. No Poisson o risco é 2,2 vezes o da base.
- **Explica o tipo de vínculo:** com cv ≤ 0,35, autônomo, empresário e assalariado ficam todos em 8% a 10%.
- **Não afeta o atraso.** O degrau é moderado e a forma é um pouco irregular.
- **Novos:** 269 pedidos (207 sem outra regra).
- **Ação:** o segmento fica no ponto de equilíbrio (cerca de 0% por real). Negamos por prudência; a diferença de lucro é de só R$ 4 mil.

### P08. Restrição ativa: afeta o atraso, não o calote
Clientes com 1 restrição ativa e sem outros fatores de risco têm inadimplência de 7%, contra 10% da média, mas atrasam em 46% dos casos, contra 23%. Afeta 203 clientes.

- **Regra de calote:** no bruto, 43% (127 aprovados). Mas 30% desses clientes têm os perfis P02 ou P03, contra 3% dos clientes sem restrição. A restrição é um marcador desses perfis.
- **Atraso:** sobe para 46–48%. No logit com controles o coeficiente é +0,9 a +1,0 (p ≤ 0,03). Por parcela, 18,3% contra 9,2%.
- **2 ou mais restrições:** nunca foram aprovadas, então não há evidência.
- **Ação:** aprovar 1 restrição quando não houver outro fator de risco (margem de cerca de +3% a +5% por real). Manter negado com 2 ou mais.

### P09. Renda declarada baixa (R$ 1.500 a R$ 2.000) não aumenta o risco
Clientes com renda declarada entre R$ 1.500 e R$ 2.000 e sem outros fatores de risco têm inadimplência de 7% a 12%, contra 9% a 11% da média. Afeta 120 clientes.

- **Evidência:** o nível da renda não tem efeito depois de controlar a sobra (Poisson: RR 1,03, p=0,95). A amostra é pequena (56 a 63 aprovados).
- **Fora da evidência:** o piloto nunca aprovou renda ≤ R$ 1.500 (48 novos).

### P10. Aposentados têm risco menor
Clientes aposentados têm inadimplência de 6%, contra 9% da média dos clientes limpos. Afeta 196 clientes.

- **Efeito:** RR de 0,73 no Poisson. No logit dos maduros o coeficiente é −0,76 (p=0,016). Dentro das mesmas faixas de idade, idade não explica o efeito.
- **Ação:** nenhuma regra nova. Aposentados nunca têm cv alto e quase sempre passam nas regras.

### P11. Histórico curto no bureau (menos de 36 meses), confiança baixa
Clientes com menos de 36 meses de histórico no bureau têm inadimplência de 11%, contra 7% da média dos clientes limpos. Afeta 619 clientes.

- **Evidência:** RR de 1,37 (p=0,01). O efeito é ruidoso e sem degrau nítido (o pico fica entre 21 e 24 meses). Ao incluí-lo, o resíduo dos clientes com histórico curto (menos de 12 meses) diminui.
- **Ação:** não usar. O risco fica muito abaixo do ponto de equilíbrio.

### P12. CEP iniciado em 1 a partir de abril de 2025 (ATRIBUTO SENSÍVEL)
Clientes com CEP iniciado em 1 que pediram crédito a partir de abril de 2025 têm inadimplência de 20% a 24%, contra 8% a 9% da média. Afeta 102 clientes.

- **Efeito:** não existia antes de abril de 2025 (9,3% contra 10,6%). No Poisson o risco é 2,25 vezes o da base (p<0,001).
- **Não afeta o atraso.**
- **Ação:** NÃO usar (usa_atributo_sensivel=true). O custo de não usar está na seção 4.

### Mecânica de calote e atraso (regras do gerador, sem segmento)
- **Calote absorvente:**
  - Uma parcela não paga há mais de 60 dias nunca é paga depois.
  - Nenhum atraso pago passa de 60 dias, e nenhum fica entre 1 e 4 dias.
  - Pagamento em dia ocorre de 0 a 5 dias ANTES do vencimento.
- **Momento do calote:** `k = floor(U(0; 0,6×prazo)) + 1`, igual em todos os segmentos de risco. Nenhum calote acontece depois de 60% do prazo.
- **Três classes de cliente:** em dia 64,6%, atrasa 17,8%, calote 17,6%.
  - Na classe "atrasa", o número de parcelas atrasadas é `round(prazo × U(0,2; 0,5))`, em posições aleatórias, com atraso de U(5, 60) dias cada.
  - Quem vai dar calote já atrasa cerca de 30% das parcelas antes.
- **Rótulo `situacao_final`:** marca "inadimplente" só depois de cerca de 90 dias, então não deve ser usado como alvo. Há 44 contratos "em_atraso" que já são calote.

### Políticas históricas (reproduzidas 100%)
- **Atual:** score > 600, renda > 2000 e 0 restrições, com teto da parcela em 30% da renda declarada. Acerta as 8.737 decisões; o valor aprovado difere em no máximo R$ 0,11.
- **Piloto:** score > 450, renda > 1500 e no máximo 1 restrição, com teto de 35% da renda declarada. Acerta as 1.263 decisões.

---

## 2. Achados refutados ou absorvidos (não são regras próprias)

| Hipótese | Por que cai |
|---|---|
| 8 ou mais consultas em 90 dias = calote | Todos os casos estão dentro do perfil P02 (177 de 177 no histórico, 38 de 38 nos novos). Com 0 a 7 consultas a curva é plana. |
| Cheque especial em 2 ou mais meses = calote | É marcador do perfil P02. Fora dele dá 15% a 23% de calote e 0 de 10 maduros. |
| Parcela acima de 30% das entradas | Proxy de "valor reduzido ao teto" (137 dos 175 casos); perde o efeito nos modelos (p=0,84). |
| Valor reduzido ao teto, ou parcela ≥ 27–30% da renda declarada | É absorvido por P04: reduzidos com pedido ≤ 6x dão 12,6%. |
| Dívida em outras instituições > 30% da renda declarada (calote) | Proxy de P05: com dívida ≤ 35% das entradas dá 2,4%. Ainda pode ter um efeito residual no atraso (30% contra 22%, n=69). |
| Tipo de vínculo e profissão | Explicados pelo cv (P07). |
| Gênero, estado civil, idade, prazo, nível do valor e da renda, saldo médio | Sem efeito nos clientes limpos. |
| Política piloto contra atual | Sem efeito próprio: o piloto só aprovou mais clientes dos perfis P02 e P03. |
| Parcela/sobra abaixo de 0,5 | Quase plano: 7% até 0,3 e 11% a 12% entre 0,3 e 0,45 (rampa leve que justifica a folga de 0,45). |

---

## 3. Gerador oculto reconstruído

```
1) Score: U(450,590) se meses_historico_bureau < 12; senão N(768,100) truncado em 1000. Não entra no desfecho.
2) Regras duras (P_calote ≈ 1):
   a) mov_saidas_sobre_entradas ≥ 0,9                                    → 1,00
   b) parcela(valor_APROVADO)/(entradas_med − saidas_med) > 0,5, ou sobra ≤ 0 → 1,00
   c) renda_declarada / entradas_med > 2                                 → ~0,92
3) Senão: P_calote = min(1; 0,076 × 4,9^[valor_SOLICITADO/entradas > 6]
                                   × 3,1^[outras_parcelas/entradas > 0,35]
                                   × 2,2^[cv_entradas > 0,35]
                                   × 0,73^[aposentado]
                                   × 1,37^[meses_bureau < 36])
   (variante sensível: × 2,25^[CEP começa com 1 e pedido ≥ abr/2025])
   Efeito multiplicativo: a interação dívida × cv não é significativa (RR 1,21, p=0,61).
4) Momento do calote: parcela floor(U(0; 0,6×prazo)) + 1; a partir dela não paga mais nada.
5) Entre quem não dá calote: P(classe atrasa) = logística(logit(0,216) + 1,05×[outras/entradas > 0,35] + 0,95×[restrições = 1]),
   o que dá 21,6% na base, ~45% com dívida alta e ~47% com 1 restrição.
   Parcelas atrasadas: round(prazo×U(0,2;0,5)), com U(5,60) dias de atraso. Em dia: pagamento de 0 a 5 dias antes do vencimento.
6) Desfecho no gabarito: em dia = +15% do valor aprovado, atraso = +5%, calote = −60%.
```

**Checagem por simulação.** Apliquei o gerador aos 6.033 aprovados do histórico e comparei calotes observados com esperados (soma de P × exposição):

| Segmento | Observado | Esperado | Razão | Maduros: observado / previsto |
|---|---|---|---|---|
| Todos | 626 | 613 | 1,02 | 17,6% / 17,0% |
| Política atual | 480 | 485 | 0,99 | 16,6% / 16,1% |
| Piloto | 146 | 128 | 1,14 | 31,7% / 29,5% |
| Saídas ≥ 0,9 | 102 | 94 | 1,08 | 100% / 100% |
| Parcela/sobra > 0,5 | 238 | 227 | 1,05 | 100% / 100% |
| Renda inflada > 2x | 25 | 22 | 1,12 | 89% / 93% |
| Valor reduzido ao teto | 159 | 152 | 1,05 | 61% / 57% |
| Pedido > 6x (sem regra da sobra) | 43 | 41 | 1,05 | 53% / 47% |
| Dívida/entradas > 0,35 | 64 | 61 | 1,05 | 31% / 28% |
| cv > 0,35 | 74 | 73 | 1,01 | 20% / 20% |
| 1 restrição | 29 | 32 | 0,92 | 53% / 55% |
| Aposentado | 47 | 45 | 1,05 | 10,9% / 11,0% |
| Safra 2024, 2025, 2026 | 110, 417, 99 | 112, 410, 92 | 0,99 a 1,08 | |
| Score ≤ 600 | 41 | 35 | 1,16 | (com o termo de bureau < 36) |
| CEP 1 a partir de abr/2025 | 35 | 23 | 1,55 | (zera com a variante sensível) |
| Parcela/sobra entre 0,3 e 0,5 | 92 | 79 | 1,17 | rampa leve |
| Dívida e cv juntos | 10 | 7,9 | 1,27 | n=29 |

O atraso simulado também bate com o observado (não-caloteiros com pelo menos 50% vencido): 22,8% na base, 44,8% com dívida alta e 46,2% com 1 restrição.

---

## 4. Política proposta para os 2.000 novos pedidos

Passos, aplicados em ordem (nenhum usa atributo sensível):

1. **Negar** se `mov_saidas_sobre_entradas ≥ 0,9` (97 pedidos).
2. **Negar** se `renda_declarada / mov_entradas_med > 2` (66).
3. **Negar** se `valor_solicitado > 6 × mov_entradas_med` (121). Não oferecer valor reduzido.
4. **Negar** se `parcelas_outras_instituicoes / mov_entradas_med > 0,35` (165).
5. **Negar** se `mov_entradas_cv > 0,35` (269). Essa regra é neutra no lucro e opcional.
6. **Negar** se `restricoes_ativas ≥ 2` (174, sem evidência). Aceitar 0 ou 1 restrição.
7. **Ficar dentro da faixa já testada pelo piloto:** score > 450 e renda declarada > 1500. Não usar os cortes de score 600 e renda 2000.
8. **Definir o valor:** `valor = min(valor_solicitado; 0,45 × sobra × (1−1,03^−prazo)/0,03; 0,30 × renda_declarada × (1−1,03^−prazo)/0,03; 30.000)`.
   - Negar se `sobra ≤ 0` ou se o valor final ficar abaixo de R$ 500.
   - O teto de 30% da renda quase não atua (a diferença é de R$ 2,6 mil); fica como trava de segurança.

**Resultado esperado** (a PD vem do gerador da seção 3; o lucro segue a pontuação do gabarito):

| | Política atual | Proposta |
|---|---|---|
| Aprovados | 1.145 | 1.287 |
| Valor total aprovado | R$ 8.856.446,13 | R$ 9.039.987,81 |
| PD esperada (média por contrato / ponderada por valor) | 15,6% / 18,1% | 7,8% / 7,9% |
| Lucro esperado | −R$ 37 mil (−0,4% por real) | +R$ 636 mil (+7,0% por real) |

- **Diferença entre as duas:** a proposta aprova 383 pedidos que a atual nega (287 com score ≤ 600, 62 com 1 restrição, 72 com renda ≤ 2000). Ela nega 241 que a atual aprova e reduz o valor de 25.
- **Sensibilidade:**
  - Aceitar 2 ou mais restrições daria +R$ 28 mil se a restrição não tiver efeito próprio, mas isso não foi testado.
  - Tirar a faixa testada (score > 450 e renda > 1500) daria +R$ 6 mil.
  - Não negar cv alto daria −R$ 4 mil, com 176 aprovações a mais.
  - A folga de 0,40 ou 0,49 na sobra muda o lucro em ±R$ 2 mil.
- **Atributo sensível (CEP 1):** com o gerador sensível, a proposta dá +R$ 599,0 mil. Negar também o CEP 1 daria +R$ 599,3 mil, ou seja, deixamos de ganhar só cerca de R$ 300. Esses clientes ficam em cerca de 17%, no ponto de equilíbrio, então não vale usar o atributo.
- **Ressalva:** a PD da política atual no histórico foi de 15,8%, com margem de +1,3% por real. Nos novos o gerador prevê −0,4% porque a carteira de outubro de 2026 tem mais pedidos acima da capacidade.

O arquivo de decisões da proposta está em `<area-de-trabalho>/discovery/decisoes_proposta.csv`.

---

## 5. Perguntas em aberto para a segunda rodada

1. **Corte exato do pedido excessivo:** fica entre 5x e 6x as entradas (de 4x a 5x dá 15%, n=24). Falta testar se o denominador real é a renda declarada (> 4x) e se a regra é um degrau ou uma rampa.
2. **Corte de saídas/entradas:** está em algum ponto entre 0,5 e 0,949. Há 1 pedido novo em 0,505, que foi aprovado.
3. **Corte da renda inflada:** está entre 2 e 3. Ficam incertos 5 novos entre 1,8 e 2 e 6 entre 2 e 3.
4. **2 ou mais restrições (174 novos, 123 sem outra regra):** não há evidência histórica. Esta é a maior aposta pendente (+R$ 28 mil se forem neutras).
5. **Score ≤ 450 e renda ≤ R$ 1.500 (52 novos):** ficam fora do que o piloto testou.
6. **cv:** falta definir se o corte é 0,30 ou 0,35 (o perfil por faixa é irregular) e se o lucro desse segmento é de fato zero.
7. **Histórico no bureau < 36 meses ou 21 a 30 meses:** efeito fraco, sem degrau e escolhido depois de olhar os dados.
8. **Rampa de parcela/sobra entre 0,3 e 0,5:** observado contra esperado é 1,17. Falta ver se existe um termo contínuo e se uma folga de 0,40 é melhor.
9. **Atraso residual com dívida > 30% da renda declarada:** 30% contra 22% (n=69). Pode haver um segundo termo de atraso.
10. **Interação entre dívida e cv** (observado contra esperado de 1,27, n=29) e resíduo do piloto (1,14).
11. **Choque regional do CEP 1:** falta saber se continua em outubro de 2026. Não afeta a decisão.
12. **Prazo de 36 meses:** ainda não tem nenhum contrato maduro, então o gerador foi suposto igual aos demais prazos (observado contra esperado de 0,85 na exposição).
