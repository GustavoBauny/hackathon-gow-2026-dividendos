/* Motor do simulador do painel: refaz a política proposta (src/politica.py, politica_nova) no navegador.
 *
 * Dados: output/simulador.json, gerado por src/simulador.py.
 * Com os parâmetros padrão, usa os resultados exatos do pipeline e reproduz o arquivo de decisões pedido a pedido.
 * Quando o analista muda um teto do passo 4 ou a margem do passo 5, recalcula o valor ótimo com a chance de
 * calote do modelo de R$ 100 em R$ 100 (a grade), como o pipeline faz.
 * Funciona no navegador (window.Simulador) e no Node (module.exports), para o teste automático.
 */
(function (root) {
  "use strict";
  const TAXA = 0.03;
  const PONTOS_GRADE = 24;

  function decodificarGrade(b64) {
    let bytes;
    if (typeof atob === "function") {
      const bin = atob(b64);
      bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    } else {
      bytes = new Uint8Array(Buffer.from(b64, "base64"));
    }
    const u16 = new Uint16Array(bytes.length / 2);
    for (let i = 0; i < u16.length; i++) u16[i] = bytes[2 * i] | (bytes[2 * i + 1] << 8);  // little-endian
    const pd = new Float64Array(u16.length);
    for (let i = 0; i < u16.length; i++) pd[i] = u16[i] / 65535;
    return pd;
  }

  const margemPorReal = (pd, a, G) => (1 - pd) * (G.em_dia * (1 - a) + G.atraso * a) - G.calote * pd;
  const valorMaxPorParcela = (parc, prazo) => parc * (1 - Math.pow(1 + TAXA, -prazo)) / TAXA;
  const dispara = (x, corte, nega) => x != null && (nega === "maior" ? x > corte : x < corte);

  /* Chance de calote do pedido i para o valor v, a partir da grade (R$ 500, 600, ... e o valor pedido). */
  function pdNoValor(D, grade, i, v) {
    const P = D.pedidos, ini = P.grade_ini[i], n = P.grade_n[i];
    const vmax = Math.min(P.valor_solicitado[i], D.valor_max);
    const nCentenas = Math.floor(vmax / 100) - 4;           // 500, 600, ..., floor(vmax/100)*100
    const valorK = k => (k < nCentenas ? 500 + 100 * k : vmax);
    if (v <= 500) return grade[ini];
    const pos = (v - 500) / 100;
    let k = Math.floor(pos);
    if (k >= n - 1) return grade[ini + n - 1];
    if (k >= nCentenas - 1) k = nCentenas - 1;               // entre a última centena e o valor pedido
    const v0 = valorK(k), v1 = valorK(k + 1);
    if (v1 <= v0) return grade[ini + k];
    const t = Math.min(Math.max((v - v0) / (v1 - v0), 0), 1);
    return grade[ini + k] + t * (grade[ini + k + 1] - grade[ini + k]);
  }

  /* Passo 5: entre 24 valores até o teto, o de maior resultado esperado (empate técnico: fica o maior). */
  function valorOtimo(D, grade, i, teto, P) {
    const G = D.ganhos, a = D.pedidos.atraso[i];
    let melhorEv = -Infinity;
    const cands = [];
    for (let j = 0; j < PONTOS_GRADE; j++) {
      let v = teto * (1 - j / PONTOS_GRADE);
      if (j > 0) v = Math.floor(v / 100) * 100;
      if (v < D.valor_min) continue;
      const pd = pdNoValor(D, grade, i, v);
      const ev = v * margemPorReal(pd, a, G);
      cands.push([v, pd, ev]);
      if (ev > melhorEv) melhorEv = ev;
    }
    if (!cands.length) return { aprova: false, valor: 0, pd: null, ev: 0 };
    const limite = melhorEv - P.tolerancia_ev * Math.abs(melhorEv);
    const [v, pd, ev] = cands.find(c => c[2] >= limite);
    const aprova = isFinite(ev) && ev > P.margem_min * v;
    return { aprova, valor: aprova ? Math.round(v * 100) / 100 : 0, pd, ev: aprova ? ev : 0 };
  }

  /* Decide os 2.000 pedidos com os parâmetros P (mesmas chaves de Parametros; null = regra desligada). */
  function simular(D, grade, P, opcoes = {}) {
    const pad = D.parametros_padrao, PE = D.pedidos, n = PE.id.length;
    const tetosPadrao = ["teto_parcela_sobre_sobra", "teto_comprometimento", "teto_parcela_sobre_entradas"]
      .every(k => P[k] === pad[k]);
    const passo5Padrao = !opcoes.forcarCalculo && tetosPadrao && P.margem_min === pad.margem_min
      && P.tolerancia_ev === pad.tolerancia_ev;
    const regras2 = D.regras.filter(r => r.passo === 2), regras3 = D.regras.filter(r => r.passo === 3);
    const out = [];
    const nega = (r, i) => {
      if (P[r.id] == null) return false;
      if (P[r.id] === pad[r.id]) return PE.dispara_padrao[r.id][i] === 1;
      return dispara(PE.medidas[r.id][i], P[r.id], r.nega);
    };
    for (let i = 0; i < n; i++) {
      const res = { aprova: false, valor: 0, passo: 0, regra: null, pd: null, ev: 0 };
      out.push(res);
      if (!PE.tem_bureau[i]) { res.passo = 1; continue; }
      const r2 = regras2.find(r => nega(r, i));
      if (r2) { res.passo = 2; res.regra = r2.id; continue; }
      const r3 = regras3.find(r => nega(r, i));
      if (r3) { res.passo = 3; res.regra = r3.id; continue; }
      if (passo5Padrao) {
        res.passo = PE.p5_passo[i];
        res.aprova = PE.p5_aprova[i];
        res.valor = PE.p5_valor[i];
        res.pd = PE.p5_pd[i];
        res.ev = PE.p5_ev[i];
        if (res.passo === 4) res.regra = "teto";
        continue;
      }
      const teto = tetosPadrao ? (PE.teto_padrao[i] ?? NaN) : Math.floor(Math.min(
        PE.valor_solicitado[i], D.valor_max,
        valorMaxPorParcela(P.teto_parcela_sobre_sobra * PE.sobra[i], PE.prazo[i]),
        valorMaxPorParcela(P.teto_comprometimento * PE.renda[i], PE.prazo[i]),
        PE.entradas_min[i] == null ? NaN : valorMaxPorParcela(P.teto_parcela_sobre_entradas * PE.entradas_min[i], PE.prazo[i]),
      ) * 100) / 100;
      if (teto < D.valor_min) { res.passo = 4; res.regra = "teto"; continue; }
      if (!isFinite(teto)) { res.passo = 5; continue; }
      const o = valorOtimo(D, grade, i, teto, P);
      Object.assign(res, o, { passo: o.aprova ? 6 : 5 });
    }
    return out;
  }

  /* Evidência do histórico para o pedido i, liberado por regras que o negavam no padrão. */
  function evidenciaLiberado(D, P, i) {
    const pad = D.parametros_padrao, PE = D.pedidos;
    let taxa = null, n = 0, alguma = false;
    for (const r of D.regras) {
      if (PE.dispara_padrao[r.id][i] !== 1) continue;
      if (P[r.id] != null && dispara(PE.medidas[r.id][i], P[r.id], r.nega)) continue;  // ainda negaria
      alguma = true;
      const ev = D.evidencia[r.id];
      const e = P[r.id] == null ? ev.grupo_padrao : ev.faixas[r.valores.indexOf(P[r.id])];
      if (e && e.pd != null && e.n >= D.n_min_evidencia && (taxa == null || e.pd > taxa)) { taxa = e.pd; n = e.n; }
    }
    return alguma ? { taxa, n } : null;
  }

  /* Totais e comparação com a proposta oficial e com a política atual. */
  function resumir(D, res, P) {
    const PE = D.pedidos, G = D.ganhos;
    let aprovados = 0, valor = 0, reduzidos = 0, ev = 0, evAtual = 0, difOficial = 0, difAtual = 0;
    let liberados = 0, liberadosSemEvidencia = 0, ajusteHistorico = 0;
    const porRegra = {}, porPasso = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0 }, mudancas = [];
    res.forEach((r, i) => {
      porPasso[r.passo] = (porPasso[r.passo] || 0) + 1;
      if (r.regra) porRegra[r.regra] = (porRegra[r.regra] || 0) + 1;
      evAtual += PE.atual_ev[i] || 0;
      const decisao = r.aprova ? "APROVADO" : "NEGADO";
      if (r.aprova) {
        aprovados++; valor += r.valor; ev += r.ev;
        if (r.valor < PE.valor_solicitado[i] - 0.005) reduzidos++;
      }
      if (decisao !== PE.atual_decisao[i]) difAtual++;
      const mudou = decisao !== PE.oficial_decisao[i] || Math.abs(r.valor - PE.oficial_valor[i]) > 0.005;
      if (!mudou) return;
      difOficial++;
      let evid = null;
      if (r.aprova && PE.oficial_decisao[i] === "NEGADO" && (PE.oficial_passo[i] === 2 || PE.oficial_passo[i] === 3)) {
        evid = evidenciaLiberado(D, P, i);
        if (evid) {
          liberados++;
          if (evid.taxa == null) liberadosSemEvidencia++;
          else ajusteHistorico += r.valor * margemPorReal(evid.taxa, PE.atraso[i], G) - r.ev;
        }
      }
      mudancas.push({ i, id: PE.id[i], antes: PE.oficial_decisao[i], valorAntes: PE.oficial_valor[i], depois: decisao,
                      valorDepois: r.valor, passo: r.passo, regra: r.regra, pd: r.pd, evid });
    });
    const ganho = ev - evAtual;
    return { aprovados, valor, reduzidos, ev, evAtual, ganho, ganhoHistorico: ganho + ajusteHistorico, difOficial,
             difAtual, liberados, liberadosSemEvidencia, porRegra, porPasso, mudancas };
  }

  const api = { decodificarGrade, simular, resumir, pdNoValor };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Simulador = api;
})(typeof window !== "undefined" ? window : this);
