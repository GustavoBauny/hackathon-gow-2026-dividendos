# Conclusões do Desafio Fortuna — em linguagem de gente (colas do pitch)

> **Para que serve este documento:** as análises das nossas IAs ficaram muito técnicas. Aqui estão **as mesmas conclusões, mas em português simples**, para a banca entender sem esforço. Cada bloco tem um espaço **🗣️ Time — comentar ao vivo** para alguém do time explicar com as próprias palavras durante o pitch.
>
> Números atuais da solução (v3): **1.365 aprovados · R$ 9,15 mi emprestados · +R$ 608 mil de lucro esperado sobre a política atual**.

---

## 1. O problema, em uma frase

A Fortuna empresta dinheiro. **Ganha pouco quando o cliente paga (+15%) e perde muito quando leva calote (−60%)** — um calote apaga o lucro de quatro bons pagadores. A regra de aprovação dela está parada há mais de um ano e, por isso, **nega gente boa e aprova gente ruim**. Nós usamos IA para criar uma regra melhor.

> 🗣️ **Time — comentar ao vivo:** _(explique com uma frase: "o jogo não é aprovar muito, é não tomar calote")_

---

## 2. A grande conclusão (a manchete)

**A regra velha da Fortuna, na prática, não dá lucro. A nossa dá — e com folga.**

- Política atual, nos mesmos pedidos: **praticamente empatada no zero** (até leve prejuízo).
- Nossa política: **+R$ 608 mil** de lucro esperado sobre a atual.
- Num teste no passado com 10 mil empréstimos reais, a nossa rende **+R$ 3,2 milhões** a mais que a atual.

> 🗣️ **Time — comentar ao vivo:** _(é a frase de abertura do pitch — diga o número grande primeiro)_

---

## 3. O que a IA descobriu (os padrões) — em linguagem simples

A inadimplência média da base é **~17%**. A IA achou grupos muito acima e muito abaixo disso. Em todos, o segredo está **no extrato da conta** — não no score, que a regra velha idolatra.

### 🔴 Sinais de PERIGO (dão muito mais calote)
- **Quem pede mais de 6× o que entra por mês na conta → ~74% de calote.** Pede uma fortuna perto do que ganha. Reduzir o empréstimo não resolve: ele se endivida em outro lugar.
- **Quem gasta mais de 80% do que entra → ~98%.** Não sobra pra parcela nenhuma.
- **Quem declara renda maior que o dobro do que entra na conta → ~92%.** A conta desmente a renda informada.
- **Quem ficou no cheque especial em 2+ meses → ~82%.** Aperto financeiro crônico.
- **Quem teve o CPF consultado 8+ vezes em 90 dias → ~100%.** Está correndo atrás de crédito em todo canto.
- **Quem tem dívida em outros bancos acima de 35% do que entra → ~25%.**

### 🟢 OPORTUNIDADES (gente boa que a regra velha rejeita à toa)
- **1 restrição no nome, sem outros sinais → só ~2-3% de calote** (abaixo da média!). A regra atual nega todos.
- **Aposentados sem alertas → ~9%.** O grupo mais seguro.
- **Score entre 450 e 600 sem alertas → ~11-13%.** A regra atual nega todos.

### 🤯 "Parece risco, mas não é"
- **Score alto NÃO protege:** quem tem score 800 paga quase igual a quem tem 600. O score pesa pouco.
- **Conta nova não é risco por si só:** parece arriscada na base toda, mas só porque muita conta nova também tem os sinais vermelhos acima. Sem esses sinais, paga como a média.

> 🗣️ **Time — comentar ao vivo:** _(escolha 2-3 padrões pra contar como história; o de "pede 6× o que ganha" e o de "1 restrição paga bem" são os mais fortes)_

---

## 4. Como a nossa regra decide (a política)

São 6 passos, aplicados em ordem; o primeiro que reprova encerra:

1. **Consulta o bureau.** Se não responder, nega por segurança.
2. **Faixas sem histórico:** nega 2+ restrições, score muito baixo ou renda muito baixa.
3. **Sinais de alerta:** nega os perfis vermelhos do item 3 (cheque especial, gasta demais, pede 6×, etc.).
4. **Capacidade de pagar:** a parcela tem que caber no que sobra na conta.
5. **Risco × retorno:** a IA calcula a chance de calote e escolhe o **valor** que dá mais lucro. Se nenhum valor compensa, nega.
6. **Aprova** o valor escolhido (que pode ser menor que o pedido).

> 🗣️ **Time — comentar ao vivo:** _(reforce: "a IA sugere, o analista decide" — cada passo é uma regra visível)_

---

## 5. De onde vem o lucro (quanto cada frente rende)

| Frente | Pedidos | Ganho |
|---|---|---|
| **Negar quem a regra atual aprovava** (evitar calote) | 199 | **+R$ 407 mil** |
| Aprovar bom pagador que a atual negava | 419 | +R$ 139 mil |
| Emprestar menos pra quem é risco médio | 63 | +R$ 62 mil |

A maior fatia é **cortar as aprovações ruins** da política atual — ou seja, **evitar calote vale mais do que aprovar mais gente**.

> 🗣️ **Time — comentar ao vivo:** _(destaque: o maior ganho é NEGANDO os certos, não aprovando mais)_

---

## 6. Por que a política atual erra

Ela olha os **sinais errados**: score e renda *declarada* (a que o cliente diz). Nós olhamos o **comportamento real da conta** (o que de fato entra e sai). Por olhar o sinal errado, a atual **nega quem pagaria** (ex.: 1 restrição = 2-3% de calote) e **aprova quem não paga** (score alto, mas gasta tudo que ganha).

> 🗣️ **Time — comentar ao vivo:** _(essa é a dor que o cliente descreveu no começo — agora provada com dados)_

---

## 7. Justiça: não discriminamos — e provamos

- Nossa regra **não usa** CEP, gênero, idade nem estado civil. Decide por **capacidade de pagar**, não por quem a pessoa é.
- **Testamos usar esses dados** (num experimento à parte): o resultado é que eles **não ajudam a ganhar dinheiro** (ficou até um pouco pior) **e discriminam** — passam a reprovar gente pelo bairro (CEP). Por isso ficaram de fora.
- Conseguimos **olhar qualquer cliente negado no olho** e explicar o porquê em uma frase.

> 🗣️ **Time — comentar ao vivo:** _(resposta pronta se a banca perguntar sobre viés/justiça — "testamos, não ajuda e discrimina, por isso não usamos")_

---

## 8. Onde está a IA (cuidado com a pegadinha)

A IA é o **modelo treinado nos 10 mil empréstimos antigos**. Ele faz duas coisas: **descobre os padrões** (os grupos acima) e **decide** (estima a chance de calote de cada cliente e escolhe o valor). ⚠️ **Não dizer** "usamos o Claude/ChatGPT pra escrever o código" como resposta — pela regra, isso não conta. A IA que decide é o **modelo**.

> 🗣️ **Time — comentar ao vivo:** _(decore: "a IA é o modelo que aprendeu nos 10 mil e decide cada pedido; o Claude foi só ferramenta de código")_

---

## 9. Qualidade técnica (se perguntarem "e se o bureau cair?")

A API do bureau falha de propósito. Nosso código **tenta de novo com espera crescente**, tem **cache**, e **nega com segurança** quem fica sem dado. Na execução real: **112 falhas da API absorvidas, 0 problemas**.

> 🗣️ **Time — comentar ao vivo:** _(número de efeito: "a API deu 112 erros, tratamos todos, zero falha")_

---

## 10. Respostas rápidas pra banca (perguntas prováveis)

- **"Dá pra confiar que não é sorte?"** → Testamos em dados que o modelo nunca viu (fora do tempo, nota de pontaria 0,88) e em simulações repetidas. Não é sorte.
- **"Por que negar 2+ restrições se 1 restrição paga bem?"** → Ninguém com 2+ foi aprovado no histórico, então não temos como medir. Preferimos não apostar; a decisão fica com o analista.
- **"Vocês acertam todos os clientes?"** → Não, e ninguém acerta — o futuro é incerto. O jogo é a **carteira dar lucro no total**, errando menos e mais barato que a regra velha. E dá: +R$ 3,2 mi no teste real.

> 🗣️ **Time — comentar ao vivo:** _(treinem essas 3 — são as que mais caem)_

---

_Documento de apoio ao pitch. Todos os números saem da solução do time (`output/resumo.json` e `output/avaliacao.json`). Dados fictícios do desafio._
