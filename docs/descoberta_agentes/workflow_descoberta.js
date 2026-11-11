export const meta = {
  name: 'fortuna-pattern-discovery',
  description: 'Discover and adversarially verify hidden default/late-payment rules in Fortuna credit history',
  phases: [
    { title: 'Find', detail: '7 analysts, one per angle, on the 10k historical requests' },
    { title: 'Verify', detail: 'one adversarial verifier per analyst' },
    { title: 'Synthesize', detail: 'dedupe, rank, reconstruct generator, propose policy' },
  ],
}

const S = '<area-de-trabalho>'
const REPO = '<repo>'
const PY = `${REPO}/.venv/bin/python -I`

const CTX = `
CONTEXT (GOW hackathon 2026, "Fortuna Crédito" challenge; deadline today 15:30, so be efficient: aim to finish in ~15-20 minutes of work).
Fortuna is a fintech that lends personal credit (R$500 to R$30,000, 3%/month, Price table: parcela = valor*0.03/(1-1.03^-prazo); prazo in {6,12,18,24,36}).
Current policy (the baseline we are scored against): approve iff bureau score > 600 AND renda_declarada > 2000 AND restricoes_ativas == 0; amount capped so parcela <= 30% of renda_declarada (in history, amount was reduced to that cap rather than denied).
A 6-month PILOT (politica_aplicada='piloto', requests Oct-2025..Mar-2026, ~half the requests in that window) approved with looser criteria, so history contains approved clients the current policy would deny. Pilot is the only evidence on those segments.
THE DATA IS SYNTHETIC: the organizers generated it with HIDDEN RULES and hold an answer key ("gabarito") for 2,000 new requests: for each, whether the client would pay on time (+15% of approved amount), pay late (+5%), or default (-60%). The outcome depends on the APPROVED AMOUNT too ("approving more than the client can pay increases default risk"). Teams are scored on (a) total profit of their decisions vs the current policy and (b) how many of the hidden rules they discover and explain correctly. So the goal is to RECOVER THE GENERATING RULES as precisely as possible: exact variables, thresholds, interactions, effect sizes, and how default/late depends on the approved amount.

DATA (read-only parquet snapshots, already built; load with pandas):
- ${S}/data/hist_base.parquet : 10,000 historical requests, one row each, with request + cadastro + bureau + account-movement features + censoring-aware target columns. Key columns: id_pedido, id_cliente, data_pedido, valor_solicitado, prazo_meses, decisao ('aprovado'/'negado'), valor_aprovado, politica_aplicada ('atual'/'piloto'), situacao_final, renda_declarada, profissao, tipo_vinculo, data_abertura_conta, genero, data_nascimento, estado_civil, cep, score, restricoes_ativas, parcelas_outras_instituicoes, consultas_90_dias, meses_historico_bureau, mov_* (12-month account summaries: mov_meses, mov_entradas_med, mov_entradas_cv, mov_salario_med, mov_frac_meses_salario, mov_saidas_med, mov_saldo_medio_med, mov_saldo_minimo_min, mov_dias_cheque_total, mov_meses_cheque, mov_frac_meses_cheque, mov_dias_cheque_ult3, mov_entradas_ult3, mov_saldo_medio_ult3, mov_saidas_sobre_entradas, mov_tendencia_entradas, mov_frac_salario_nas_entradas), idade, meses_conta, parcela_solicitada, renda_real, renda_decl_sobre_real (= renda_declarada / mean monthly total_entradas), divida_outras_sobre_renda; target (approved only): n_vencidas, n_observaveis, calote_obs (bool), atraso_obs (bool: any installment paid/owed late), n_parcelas_atraso, k_evento (installment # where default started), exposicao (0..1 fraction of the default risk window already observed), maduro (exposicao>=1), frac_vencida.
- ${S}/data/novos_base.parquet : the 2,000 NEW requests (same feature columns, bureau filled from the API; no decision/outcome).
- Raw tables: ${S}/data/{clientes,pedidos,movimentacao_mensal,bureau,parcelas}.parquet (movimentacao_mensal: id_cliente, mes_referencia, total_entradas, entradas_salario, total_saidas, saldo_medio, saldo_minimo, dias_cheque_especial; 12 months before each request; each client has exactly one request. parcelas: id_pedido, numero_parcela, data_vencimento, valor_parcela, data_pagamento, dias_atraso).
- Teammate code you may import (sys.path.insert(0, '${REPO}/src')): features.py (parcela_price, valor_max_por_parcela, montar_base), target.py (construir_alvo, DATA_CORTE=2026-09-30), modelo.py (km_relativo, discrete-time hazard model). Do NOT edit anything in ${REPO}.

CENSORING (critical): data cut-off 2026-09-30; many contracts are still running. A contract "on time after 1 month" is NOT proof of a good payer. Teammate's measured facts (verify if relevant): no installment paid late was ever paid more than 60 days late, so an unpaid installment >60 days overdue = default (calote); defaults start between installment 1 and ~ceil(0.6*prazo). Use one of: (1) the mature subset (maduro==True, ~1,957 approved contracts, default ~17.6%), (2) exposure-adjusted rate = sum(calote_obs)/sum(exposicao), or (3) Kaplan-Meier (modelo.km_relativo). Report which. Overall approved: 6,033 (5,038 'atual', ~1,126 'piloto'); naive calote_obs rate 10.4% (biased low).
For "late" (atraso) analysis among non-defaulters, prefer contracts with a large fraction already due (frac_vencida >= 0.5) or fully finished.

HOW TO WORK: write your analysis scripts ONLY under ${S}/agents/<your-label>/ (create it) and run them with: ${PY} <script>. Do not run python from inside the data dir. Python has pandas, numpy, scikit-learn, lightgbm, statsmodels, pyarrow. Prefer crisp, interpretable findings (thresholds found by scanning cut points, step changes, interactions) over vague correlations; synthetic generators usually use clean thresholds (round numbers) and simple combinations. For each finding quantify: segment definition (exact), # historical requests in segment, # approved with outcome, censoring-adjusted default rate in segment vs. the complement / baseline, late-payment rate if relevant, and # of the 2,000 new requests in the segment. Check whether the effect holds controlling for the obvious confounders (score, restricoes, income). Note sensitive attributes (genero, idade, estado_civil, cep): you may test them, but flag uses_protected_attribute=true.
Write business phrasing in Brazilian Portuguese in the format: "Clientes com [característica] têm inadimplência de [N]%, contra [N]% da média. Afeta [N] clientes."
`

const FINDING = {
  type: 'object',
  properties: {
    id: { type: 'string', description: 'short slug' },
    titulo_negocio: { type: 'string', description: 'pt-BR business sentence in the required format' },
    regra_tecnica: { type: 'string', description: 'exact definition: variables, formulas, thresholds' },
    n_hist_segmento: { type: 'number' },
    n_aprovados_com_desfecho: { type: 'number' },
    taxa_calote_segmento: { type: 'number', description: 'censoring-adjusted, 0..1' },
    taxa_calote_referencia: { type: 'number', description: 'complement or baseline, 0..1' },
    taxa_atraso_segmento: { type: ['number', 'null'] },
    metodo_taxa: { type: 'string' },
    n_novos_segmento: { type: 'number' },
    nitidez_limiar: { type: 'string', description: 'how sharp the threshold is (step vs gradual), with neighboring cut evidence' },
    controle_confundidores: { type: 'string' },
    acao_politica_sugerida: { type: 'string' },
    usa_atributo_sensivel: { type: 'boolean' },
    confianca: { type: 'string', enum: ['alta', 'media', 'baixa'] },
  },
  required: ['id', 'titulo_negocio', 'regra_tecnica', 'n_hist_segmento', 'n_aprovados_com_desfecho', 'taxa_calote_segmento', 'taxa_calote_referencia', 'metodo_taxa', 'n_novos_segmento', 'nitidez_limiar', 'controle_confundidores', 'acao_politica_sugerida', 'usa_atributo_sensivel', 'confianca'],
}

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: { type: 'array', items: FINDING },
    nulos: { type: 'array', items: { type: 'string' }, description: 'hypotheses tested that showed NO effect (useful too)' },
    scripts: { type: 'array', items: { type: 'string' } },
    notas: { type: 'string' },
  },
  required: ['findings', 'nulos', 'scripts', 'notas'],
}

const VERIFIED_SCHEMA = {
  type: 'object',
  properties: {
    verificados: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          veredito: { type: 'string', enum: ['confirmado', 'refinado', 'refutado'] },
          finding: FINDING,
          justificativa: { type: 'string', description: 'what you re-computed, robustness checks (mature vs exposure, atual vs piloto, controlling confounders, neighbor thresholds), why refined/refuted' },
        },
        required: ['id', 'veredito', 'finding', 'justificativa'],
      },
    },
    novos_achados: { type: 'array', items: FINDING, description: 'anything important you noticed that the analyst missed' },
    scripts: { type: 'array', items: { type: 'string' } },
  },
  required: ['verificados', 'novos_achados', 'scripts'],
}

const PRIOR = `Teammate's earlier quick pass claimed (treat as unverified hypotheses, do not just confirm; refine thresholds and quantify): default 70%-100% for: overdraft (cheque especial) in 2+ of the last 12 months; outflows > 80% of inflows; 8+ CPF bureau queries in 90 days; declared income > 2x real inflows; installment > 50% of monthly surplus (inflows - outflows) -> default jumps to ~100%. Lowest score ever approved: 452; lowest income approved: 1,550; 2+ restrictions never approved.`

const DIMENSIONS = [
  { key: 'bureau', brief: `ANGLE: BUREAU variables (score, restricoes_ativas, consultas_90_dias, meses_historico_bureau, parcelas_outras_instituicoes and debt ratio parcelas_outras/renda). Find thresholds and nonlinearities. Use the pilot to measure regions the current policy denies (score <= 600, 1 restriction, income <= 2000): is score 550-600 actually fine? Is 1 restriction actually bad? Is thin bureau history (few meses_historico_bureau) bad or neutral ("good payers with little credit movement get low scores" is the client's suspicion)? Check whether score matters at all once account-movement signals are controlled. ${PRIOR}` },
  { key: 'movimentacao', brief: `ANGLE: ACCOUNT MOVEMENT (movimentacao_mensal raw table + mov_* features). Build your own richer features from the raw monthly table (e.g., months with overdraft, max overdraft days, negative saldo_minimo months, salary present every month vs gaps, salary drop/loss in the last 3 months, inflow volatility, outflow/inflow ratio per month and its max, saldo_medio relative to parcela, trend in balances, months of account history). The manual explicitly says less obvious patterns are COMBINATIONS of behaviours in account movement. Hunt for those combinations and their exact thresholds. ${PRIOR}` },
  { key: 'cadastro_renda', brief: `ANGLE: CADASTRO & INCOME TRUTHFULNESS: renda_declarada vs real inflows (mov_entradas_med, mov_salario_med) -> find the exact ratio threshold where risk jumps; tipo_vinculo (assalariado/autonomo/empresario/aposentado) and profissao effects, also interacting with income volatility; account age (meses_conta / data_abertura_conta) and number of movement months; valor_solicitado relative to income. Also test sensitive attributes (genero, idade, estado_civil, cep region) and FLAG them. ${PRIOR}` },
  { key: 'valor_capacidade', brief: `ANGLE: HOW OUTCOME DEPENDS ON THE APPROVED AMOUNT (most important for the amount decision). Find the functional form: default vs parcela/renda_declarada, parcela/renda_real (mean inflows or salary), parcela/(inflows - outflows) "sobra", (parcela + parcelas_outras_instituicoes)/income, prazo. Look for a hard threshold (e.g., default ~certain above X% of surplus) and where it lies precisely. Exploit natural experiments: under the current policy the amount was REDUCED to the 30%-of-declared-income cap for some clients (valor_aprovado < valor_solicitado) while pilot clients may have received the full amount; compare outcomes. Determine the best rule to SIZE the approved amount (max safe parcela as a function of which income measure), and whether reducing the amount actually rescues risky clients. Also check late-payment (atraso) dependence on commitment. ${PRIOR}` },
  { key: 'atraso_censura', brief: `ANGLE: LATE PAYMENT vs ON-TIME and CENSORING MECHANICS. (1) Verify censoring facts: max days late among paid installments; distribution of the installment where default starts relative to prazo (is it uniform in [1, ceil(0.6*prazo)]?); does default ever start later? (2) Who pays LATE (the +5% vs +15% difference): find the variables and thresholds driving atraso among non-defaulters (use contracts with frac_vencida>=0.5 or finished). (3) Is there a segment with high late rate but low default, which is still profitable (EV per R$ = (1-PD)*(0.15*(1-L)+0.05*L) - 0.60*PD)? Compute break-even PD (~20% if L=0). (4) Check whether the situacao_final labels agree with the parcelas table.` },
  { key: 'mineracao_regras', brief: `ANGLE: AUTOMATED RULE MINING to catch interactions the other analysts may miss. On approved contracts with censoring handled (mature subset, or weight by exposicao / use exposure-adjusted rates), fit shallow decision trees (depth 3-5, min leaf ~50) and gradient boosting with feature importance / partial dependence, then extract crisp leaf rules with high or very low default. Include engineered ratios (parcela/renda, parcela/sobra, renda_decl/real, saidas/entradas, overdraft months, consultas). Report the top interpretable rules and any 2-way interaction (e.g., autonomo AND income volatility, low score AND thin history). Also report which features carry NO signal. ${PRIOR}` },
  { key: 'auditoria_politica_atual', brief: `ANGLE: AUDIT OF THE CURRENT POLICY. Quantify (censoring-adjusted) where it errs: (a) good payers it denies — using pilot approvals of clients the current rules would have denied (which denial reason: score<=600, income<=2000, restriction, parcela>30%?) and their default rates by reason; (b) bad payers it approves — segments inside current-policy approvals with default > ~20% (break-even). Estimate expected profit per request of the current policy vs. a policy that adds/removes each rule, on the historical data (EV: +15% on time, +5% late, -60% default, of approved amount). Also apply the current policy to novos_base.parquet and report how many of the 2,000 new requests it approves and the total amount (this is our baseline).` },
]

function finderPrompt(d) {
  return `${CTX}\n\nYOUR ASSIGNMENT — ${d.brief}\n\nYour label (use for your scripts folder): ${d.key}. Return 4-10 high-quality findings (fewer if the angle truly has less), each fully quantified, plus the null results.`
}

function verifierPrompt(d, res) {
  return `${CTX}\n\nYOU ARE AN ADVERSARIAL VERIFIER. Another analyst (angle: ${d.key}) produced the findings below. Independently RE-IMPLEMENT each computation from the parquet files (do not trust their numbers or scripts) and try to REFUTE each one: (1) do the numbers reproduce? (2) robustness: mature subset vs exposure-adjusted; atual vs piloto; different time periods; (3) confounding: does the effect survive controlling for score, restricoes, income, overdraft, outflow ratio and commitment? is it just a proxy of another stronger rule? (4) threshold precision: scan neighbouring cut points and correct the threshold if the step is elsewhere; (5) sample size: is the segment too small to trust? Mark each as confirmado / refinado (with corrected definition and numbers in 'finding') / refutado. Add anything important they missed to novos_achados. Use label verify-${d.key} for your scripts folder.\n\nFINDINGS TO VERIFY (JSON):\n${JSON.stringify(res, null, 1)}`
}

phase('Find')
const verified = await pipeline(
  DIMENSIONS,
  d => agent(finderPrompt(d), { label: `find:${d.key}`, phase: 'Find', schema: FINDINGS_SCHEMA }),
  (res, d) => res ? agent(verifierPrompt(d, res), { label: `verify:${d.key}`, phase: 'Verify', schema: VERIFIED_SCHEMA }).then(v => ({ dim: d.key, finder: res, verified: v })) : null,
)

const ok = verified.filter(Boolean)
log(`${ok.length}/${DIMENSIONS.length} angles finished find+verify`)

phase('Synthesize')
const synthesis = await agent(`${CTX}

YOU ARE THE SYNTHESIZER. Below are the verified findings from ${ok.length} analyst+verifier pairs (angles: ${ok.map(o => o.dim).join(', ')}). Tasks:
1. Deduplicate and merge into ONE canonical list of patterns (drop refuted ones; use the verifier's refined numbers). Re-run quick checks yourself on any conflicting numbers (scripts under ${S}/agents/synthesis/).
2. Rank by importance (impact on profit = how many clients x how much default difference).
3. RECONSTRUCT THE MOST LIKELY HIDDEN GENERATOR: a compact, explicit description of how outcome (default / late / on time) is produced from features AND the approved amount (base rate, each rule's effect, interactions, amount dependence). Then sanity-check it: simulate it on the historical approved contracts and compare to observed censoring-adjusted rates by segment.
4. Propose a concrete decision policy for the 2,000 new requests that maximizes expected profit under the scoring (+15% on time, +5% late, -60% default of approved amount; denied = 0): ordered steps (deny rules with thresholds, amount-sizing rule), with the expected default rate of approved, approval count and total approved amount on novos_base.parquet, and the same for the current policy for comparison. Prefer rules that do not use sensitive attributes (genero, idade, estado_civil, cep); if a sensitive attribute carries real signal, report it separately and say what we lose by not using it.
5. List open questions / gaps worth a second round of analysis.
Write two files: ${S}/discovery/patterns.json (machine-readable: patterns list, generator, policy) and ${S}/discovery/patterns.md (pt-BR, business language for a credit analyst, each pattern in the format "Clientes com [característica] têm inadimplência de [N]%, contra [N]% da média. Afeta [N] clientes." followed by the technical rule). Return the markdown content as your final answer.

VERIFIED FINDINGS (JSON):
${JSON.stringify(ok, null, 1)}`, { label: 'synthesize', phase: 'Synthesize' })

return { synthesis, raw: ok }
