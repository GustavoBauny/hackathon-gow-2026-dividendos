/* Tela do simulador no painel. O motor de decisão fica em src/simulador.js (window.Simulador). */
(function () {
  "use strict";
  const dadosEl = document.getElementById("sim-dados");
  if (!dadosEl || !window.Simulador) return;
  const S = window.Simulador;
  const D = JSON.parse(dadosEl.textContent);
  const grade = S.decodificarGrade(D.grade_pd_u16_b64);
  const pad = D.parametros_padrao;
  let P = { ...pad };

  const fN = (v, c = 0) => Number(v).toLocaleString("pt-BR", { minimumFractionDigits: c, maximumFractionDigits: c });
  const fPct = (v, c = 0) => (v == null ? "—" : fN(v * 100, c) + "%");
  const fMil = v => (v >= 0 ? "+" : "−") + "R$ " + fN(Math.abs(v) / 1000, 0) + " mil";
  const fMi = v => "R$ " + fN(v / 1e6, 2) + " mi";
  const fBRL = v => "R$ " + fN(v, 0);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
  const delta = (v, c = 0) => (v === 0 ? "igual" : (v > 0 ? "+" : "−") + fN(Math.abs(v), c));

  const REGRA = Object.fromEntries(D.regras.map(r => [r.id, r]));
  const TETO = Object.fromEntries(D.tetos.map(t => [t.id, t]));
  const oficial = S.resumir(D, S.simular(D, grade, pad), pad);

  function textoEvidencia(e) {
    if (!e || e.n === 0) return "nenhum contrato assim no histórico, então não há desfecho para medir.";
    if (e.n < D.n_min_evidencia) return `só ${fN(e.n)} contratos no histórico (${fPct(e.pd)} de calote), pouco para concluir.`;
    return `<b>${fPct(e.pd)}</b> de calote em ${fN(e.n)} contratos do histórico.`;
  }

  // ---------------------------------------------------------------- controles
  // Regra desligada na proposta (padrão null): o controle começa desmarcado, parado no corte "ligar_em".
  function corteInicial(item) {
    if (pad[item.id] != null) return pad[item.id];
    return item.ligar_em != null ? item.ligar_em : item.valores[0];
  }

  function htmlControle(item, tipo) {
    const valores = item.valores, k = valores.indexOf(corteInicial(item));
    const liga = tipo === "regra"
      ? `<label class="sim-liga"><input type="checkbox" data-liga${pad[item.id] != null ? " checked" : ""}> <b>${esc(item.nome)}</b></label>`
      : `<b>${esc(item.nome)}</b>`;
    return `<div class="sim-regra" data-id="${item.id}" data-tipo="${tipo}">
      <div class="sim-topo">${liga}<span class="sim-cnt" data-cnt></span></div>
      <input type="range" min="0" max="${valores.length - 1}" step="1" value="${k}" data-corte aria-label="Corte: ${esc(item.nome)}">
      <div class="sim-rot" data-rot></div>
      <div class="sim-ev small muted" data-ev></div>
    </div>`;
  }
  const margens = { id: "margem_min", nome: "Resultado mínimo por real emprestado", valores: D.margens };
  document.getElementById("sim-p2").innerHTML = D.regras.filter(r => r.passo === 2).map(r => htmlControle(r, "regra")).join("");
  document.getElementById("sim-p3").innerHTML = D.regras.filter(r => r.passo === 3).map(r => htmlControle(r, "regra")).join("");
  document.getElementById("sim-p4").innerHTML = D.tetos.map(t => htmlControle(t, "teto")).join("");
  document.getElementById("sim-p5").innerHTML = htmlControle(margens, "margem");

  function rotulo(id, tipo) {
    if (tipo === "margem") return `aprova se render pelo menos ${fN(P.margem_min * 100, 1)}% do valor`;
    const item = REGRA[id] || TETO[id];
    return item.rotulos[item.valores.indexOf(P[id])];
  }

  function evidenciaControle(id, tipo) {
    if (tipo === "margem") {
      return P.margem_min === pad.margem_min ? "Folga para o erro do modelo. Mais alto, mais conservador."
        : P.margem_min > pad.margem_min ? "Mais conservador que a proposta: nega pedidos de margem apertada."
          : "Menos folga para o erro do modelo: aprova pedidos de margem apertada.";
    }
    const ev = D.evidencia[id];
    if (tipo === "teto") {
      if (P[id] === pad[id]) return "Acima deste teto, entre clientes sem sinal de alerta: " + textoEvidencia(ev.grupo_padrao);
      const e = ev.faixas[TETO[id].valores.indexOf(P[id])];
      return (P[id] > pad[id] ? "Permite parcelas acima do teto da proposta. Nessa faixa: "
        : "Passa a cortar parcelas que a proposta permite. Nessa faixa: ") + textoEvidencia(e);
    }
    const r = REGRA[id];
    if (pad[id] == null) {
      if (P[id] == null) return "<b>Desligada na proposta.</b> " + esc(r.nota_desligada || "Marque para testar.");
      const f = ev.faixas[r.valores.indexOf(P[id])];
      if (!f || f.n === 0) return "Ligada, mas não pega ninguém a mais no histórico: quem ela negaria já é negado por outra regra.";
      return "Ligada: passa a negar, entre clientes que nenhuma outra regra nega: " + textoEvidencia(f);
    }
    if (P[id] == null) return "<b>Desligada.</b> Libera quem só ela negava: " + textoEvidencia(ev.grupo_padrao);
    if (P[id] === pad[id]) return "Quem só ela nega: " + textoEvidencia(ev.grupo_padrao);
    const afrouxa = r.nega === "maior" ? P[id] > pad[id] : P[id] < pad[id];
    const e = ev.faixas[r.valores.indexOf(P[id])];
    return (afrouxa ? "Libera a faixa entre o corte da proposta e este: " : "Passa a negar a faixa entre este corte e o da proposta: ")
      + textoEvidencia(e);
  }

  // ---------------------------------------------------------------- resultado
  function motivoMudanca(m) {
    const PE = D.pedidos;
    if (m.depois === "NEGADO") {
      if (m.passo === 2 || m.passo === 3) return "passa a negar: " + esc(REGRA[m.regra].nome.toLowerCase());
      if (m.passo === 4) return "passa a negar: nem R$ 500 cabe no teto";
      return "passa a negar: risco alto para o resultado mínimo";
    }
    if (m.antes === "NEGADO") {
      const liberou = D.regras.filter(r => PE.dispara_padrao[r.id][m.i] === 1).map(r => r.nome.toLowerCase());
      if (liberou.length) return "aprova: regra afrouxada (" + esc(liberou.join(", ")) + ")";
      return "aprova: cabe no novo teto ou na nova margem";
    }
    return m.valorDepois > m.valorAntes ? "aprova valor maior" : "aprova valor menor";
  }

  const aproximado = () => ["teto_parcela_sobre_sobra", "teto_comprometimento", "teto_parcela_sobre_entradas", "margem_min"]
    .some(k => P[k] !== pad[k]);

  let mostrarTodas = false;
  function tabelaMudancas(t) {
    const el = document.getElementById("sim-mudancas");
    if (!t.mudancas.length) {
      el.innerHTML = '<p class="small muted">Nenhum pedido muda: estes são os cortes da proposta, e o simulador reproduz o arquivo de decisões pedido a pedido.</p>';
      return;
    }
    const ordem = [...t.mudancas].sort((a, b) => Math.abs(b.valorDepois - b.valorAntes) - Math.abs(a.valorDepois - a.valorAntes));
    const lista = mostrarTodas ? ordem : ordem.slice(0, 25);
    const dec = (d, v) => (d === "APROVADO" ? `<span class="ok">aprova ${fBRL(v)}</span>` : '<span class="no">nega</span>');
    const hist = m => !m.evid ? "—" : m.evid.taxa == null ? '<span class="no">sem caso parecido</span>'
      : `${fPct(m.evid.taxa)} <span class="muted">(${fN(m.evid.n)})</span>`;
    const linhas = lista.map(m => `<tr><td><button type="button" class="ex sim-ped" data-id="${m.id}">${m.id}</button></td>
      <td>${dec(m.antes, m.valorAntes)}</td><td>${dec(m.depois, m.valorDepois)}</td><td>${motivoMudanca(m)}</td>
      <td class="n">${m.pd == null ? "—" : fPct(m.pd, 1)}</td><td class="n">${hist(m)}</td></tr>`).join("");
    const mais = ordem.length > 25
      ? `<button type="button" class="ex" id="sim-todas">${mostrarTodas ? "Mostrar só as 25 maiores" : `Mostrar todas as ${fN(ordem.length)}`}</button>` : "";
    el.innerHTML = `<div class="tbl"><table><thead><tr><th>Pedido</th><th>Proposta</th><th>Simulação</th><th>Por quê</th>
      <th>Calote (modelo)</th><th>Calote no histórico</th></tr></thead><tbody>${linhas}</tbody></table></div>
      <p class="small muted">Ordenado pela mudança de valor. "Calote no histórico" vale para pedidos liberados por uma regra: é a taxa de clientes iguais no histórico.
      Clique no pedido para ver a ficha (a ficha mostra a decisão da proposta oficial).${aproximado()
        ? " Com teto ou margem diferentes da proposta, o valor ótimo é estimado pela chance de calote de R$ 100 em R$ 100;"
          + " o arquivo que o pipeline refaz com a versão aprovada pode diferir em alguns reais por pedido." : ""}</p>${mais}`;
    el.querySelectorAll(".sim-ped").forEach(b => b.addEventListener("click", () => {
      const inp = document.getElementById("pedido");
      if (inp && typeof window.mostrar === "function") { inp.value = b.dataset.id; window.mostrar(b.dataset.id); }
      document.getElementById("consulta").scrollIntoView({ behavior: "smooth" });
    }));
    const btn = document.getElementById("sim-todas");
    if (btn) btn.addEventListener("click", () => { mostrarTodas = !mostrarTodas; tabelaMudancas(t); });
  }

  function tiles(t) {
    const tile = (k, v, s, cls = "") => `<div class="tile ${cls}"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`;
    const hist = t.liberados - t.liberadosSemEvidencia > 0;
    const subHist = hist ? `${fN(t.liberados - t.liberadosSemEvidencia)} pedidos liberados com caso parecido no histórico`
      : t.liberados ? `${fN(t.liberados)} pedidos liberados sem caso parecido no histórico` : "nenhum pedido liberado por regra";
    document.getElementById("sim-tiles").innerHTML = [
      tile("Aprovados", fN(t.aprovados), `proposta: ${fN(oficial.aprovados)} (${delta(t.aprovados - oficial.aprovados)})`),
      tile("Valor aprovado", fMi(t.valor), `proposta: ${fMi(oficial.valor)}`),
      tile("Ganho sobre a atual, pelo modelo", fMil(t.ganho), `proposta: ${fMil(oficial.ganho)}`, "destaque"),
      tile("Se os liberados repetirem o histórico", hist ? fMil(t.ganhoHistorico) : "—", subHist),
      tile("Decisões diferentes da proposta", fN(t.difOficial), `da política atual: ${fN(t.difAtual)}`),
    ].join("");
  }

  function avisos(t) {
    const el = document.getElementById("sim-aviso");
    const partes = [];
    const comEvid = t.liberados - t.liberadosSemEvidencia;
    if (comEvid > 0 && t.ganhoHistorico < t.ganho - 5000) {
      partes.push(`<p><b>O modelo e o histórico discordam.</b> Pelo modelo, a simulação rende ${fMil(t.ganho)} sobre a política atual.
        Se os ${fN(comEvid)} pedidos liberados repetirem o calote de clientes iguais no histórico, o ganho cai para <b>${fMil(t.ganhoHistorico)}</b>.
        Essas regras existem porque o modelo sozinho não vê esse risco.</p>`);
    }
    if (t.liberadosSemEvidencia > 0) {
      partes.push(`<p><b>${fN(t.liberadosSemEvidencia)} pedidos aprovados sem nenhum caso parecido no histórico.</b>
        Para eles o modelo está extrapolando. Se a decisão for aprovar, o caminho seguro é um piloto pequeno e controlado.</p>`);
    }
    el.hidden = partes.length === 0;
    el.innerHTML = partes.join("");
  }

  function atualizar() {
    const res = S.simular(D, grade, P);
    const t = S.resumir(D, res, P);
    document.querySelectorAll("#simulador .sim-regra").forEach(div => {
      const id = div.dataset.id, tipo = div.dataset.tipo;
      const desligada = tipo === "regra" && P[id] == null;
      div.classList.toggle("off", desligada);
      div.classList.toggle("mudou", P[id] !== pad[id]);
      div.querySelector("[data-corte]").disabled = desligada;
      div.querySelector("[data-rot]").textContent = desligada ? "não nega ninguém" : rotulo(id, tipo);
      div.querySelector("[data-ev]").innerHTML = evidenciaControle(id, tipo);
      const n = tipo === "regra" ? (t.porRegra[id] || 0) : null;
      div.querySelector("[data-cnt]").textContent = n == null ? "" : `nega ${fN(n)}`;
    });
    document.getElementById("sim-p4-cnt").textContent = `nega ${fN(t.porPasso[4] || 0)} (nem R$ 500 cabe)`;
    document.getElementById("sim-p5-cnt").textContent = `nega ${fN(t.porPasso[5] || 0)} por risco`;
    tiles(t);
    avisos(t);
    tabelaMudancas(t);
    document.getElementById("sim-aprovado").hidden = true;
    return t;
  }

  document.querySelectorAll("#simulador .sim-regra").forEach(div => {
    const id = div.dataset.id, tipo = div.dataset.tipo;
    const valores = tipo === "margem" ? D.margens : (REGRA[id] || TETO[id]).valores;
    const range = div.querySelector("[data-corte]");
    range.addEventListener("input", () => { P[id] = valores[Number(range.value)]; atualizar(); });
    const liga = div.querySelector("[data-liga]");
    if (liga) liga.addEventListener("change", () => { P[id] = liga.checked ? valores[Number(range.value)] : null; atualizar(); });
  });

  document.getElementById("sim-padrao").addEventListener("click", () => {
    P = { ...pad };
    document.querySelectorAll("#simulador .sim-regra").forEach(div => {
      const id = div.dataset.id, tipo = div.dataset.tipo;
      const valores = tipo === "margem" ? D.margens : (REGRA[id] || TETO[id]).valores;
      div.querySelector("[data-corte]").value = tipo === "margem" ? valores.indexOf(pad[id])
        : valores.indexOf(corteInicial(REGRA[id] || TETO[id]));
      const liga = div.querySelector("[data-liga]");
      if (liga) liga.checked = pad[id] != null;
    });
    atualizar();
  });

  // ---------------------------------------------------------------- aprovação do analista
  document.getElementById("sim-aprovar").addEventListener("click", () => {
    const nome = document.getElementById("sim-analista").value.trim();
    const box = document.getElementById("sim-aprovado");
    box.hidden = false;
    if (!nome) { box.innerHTML = "<b>Informe o nome do analista que aprova esta versão.</b>"; return; }
    const t = S.resumir(D, S.simular(D, grade, P), P);
    const mudados = Object.keys(pad).filter(k => P[k] !== pad[k]);
    const registro = {
      aprovado_por: nome,
      aprovado_em: new Date().toISOString(),
      origem: "simulador do painel (output/painel.html)",
      parametros: P,
      mudancas_sobre_a_proposta: Object.fromEntries(mudados.map(k => [k, { proposta: pad[k], aprovado: P[k] }])),
      simulacao: {
        aprovados: t.aprovados, valor_aprovado: Math.round(t.valor * 100) / 100,
        ganho_sobre_atual_modelo: Math.round(t.ganho), ganho_se_liberados_repetirem_historico: Math.round(t.ganhoHistorico),
        decisoes_diferentes_da_proposta: t.difOficial, pedidos_liberados_sem_caso_no_historico: t.liberadosSemEvidencia,
      },
      como_aplicar: "python gerar_decisoes.py --parametros parametros_aprovados.json",
    };
    const json = JSON.stringify(registro, null, 2);
    try {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([json], { type: "application/json" }));
      a.download = "parametros_aprovados.json";
      document.body.appendChild(a); a.click(); a.remove();
    } catch (e) { /* sem download (ex.: página embutida): o JSON fica abaixo para copiar */ }
    box.innerHTML = `<p><b>Versão aprovada por ${esc(nome)}.</b> ${mudados.length
      ? `${fN(mudados.length)} parâmetro(s) diferente(s) da proposta, ${fN(t.difOficial)} decisões mudam.`
      : "Sem mudanças sobre a proposta."}
      O arquivo <span class="mono">parametros_aprovados.json</span> foi baixado.</p>
      <p>O pipeline só usa uma versão aprovada: <span class="mono">python gerar_decisoes.py --parametros parametros_aprovados.json</span>
      refaz o arquivo de decisões com ela, valida o formato e refaz este painel.</p>
      <details><summary>Ver o arquivo</summary><pre class="formula">${esc(json)}</pre></details>`;
  });

  atualizar();
})();
