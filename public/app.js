// Cosechas vs Cobro: ingreso con usuario y perfil, una pestaña por archivo (bucket privado "cvc" de Supabase),
// filtros dinámicos, gráficos (Chart.js), tablas por dimensión, descarga y preguntas a la IA.
const CFG = window.CVC_CONFIG;
const QS = new URLSearchParams(location.search);
const LOCAL = QS.has('local');
const sb = LOCAL ? null : window.supabase.createClient(CFG.SUPABASE_URL, CFG.SUPABASE_ANON_KEY);
const $ = id => document.getElementById(id);
const ok = ({ data, error }) => { if (error) throw new Error(error.message); return data; };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const DOMINIO = '@tiemposdac.local';
const CLAVE_INICIAL = '12345678';
const ROLES = { admin: 'Administrador', gerencia: 'Gerencia', cobro: 'Cobro', comercial: 'Comercial' };
const PESTANAS = [
  { id: 'cosecha', t: 'Cosecha', roles: ['admin', 'gerencia'] },
  { id: 'cartera_activa', t: 'Cartera Activa', roles: ['admin', 'gerencia', 'cobro'] },
  { id: 'primeros_pagos', t: 'Primeros Pagos', roles: ['admin', 'gerencia', 'cobro', 'comercial'] },
  { id: 'cono', t: 'Cono de cobranza', roles: ['admin', 'gerencia'] },
];
const slug = s => (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
  .trim().replace(/[^a-z0-9]+/g, '.').replace(/^\.|\.$/g, '');

// ---------- Colores (orden validado contra daltonismo; mora: degradado navy validado) ----------
const SERIE = ['#4B9D45', '#2E5FB8', '#F5821F', '#00A4E0', '#93BF02'];
const GRIS = '#C9CDD5';
const MORA_GRUPOS = ['Al día', '1-30 días', '31-90 días', '91-180 días', 'Más de 180', 'Cancelado'];
const MORA_COLOR = ['#8FAEDF', '#5F82BE', '#3A5E9C', '#1F3B6E', '#06255B', GRIS];
const MORA_A_GRUPO = { B0: 0, B1: 1, B2: 2, B3: 2, B4: 3, B5: 3, B6: 3, B7: 4, CANCELADO: 5 };
const M30 = new Set(['B2', 'B3', 'B4', 'B5', 'B6', 'B7']);
const M90 = new Set(['B4', 'B5', 'B6', 'B7']);

// ---------- Dimensiones ----------
const DIM = {
  sucursal: 'Sucursal', canal: 'Canal', sucursal_promotor: 'Sucursal promotor', promotor: 'Promotor',
  producto_comercial: 'Producto', producto_motor: 'Producto motor', clasificacion: 'Clasificación',
  categorizacion: 'Categorización', tipo_credito: 'Tipo de crédito', medio_captacion: 'Medio de captación',
  rango_score: 'Rango de score', rango_desembolso: 'Rango de desembolso', rango_salario: 'Rango de salario',
  rango_edad: 'Rango de edad', rango_multiplicador: 'Multiplicador', rango_antig_cliente: 'Antigüedad del cliente',
  rango_antig_credito: 'Antigüedad del crédito', rango_antig_laboral: 'Antigüedad laboral',
  rango_capacidad: 'Capacidad de pago', rango_ingreso: 'Ingreso bruto (motor)', rango_estabilidad: 'Estabilidad INSS',
  rango_edad_motor: 'Edad (motor)', perfil_motor: 'Perfil motor', politica_hit: 'Política HIT', genero: 'Género',
  plazo: 'Plazo', empleo_inss: 'En base INSS', mes_desembolso: 'Mes de desembolso', mora: 'Tramo de mora',
  rodamiento: 'Rodamiento', tipo_cartera: 'Tipo de cartera', tipo_pago: 'Tipo de pago', pago_mes: 'Pago en el mes',
  estado_promesa: 'Estado de promesa', ult_resultado: 'Último resultado de gestión', gestor: 'Gestor',
  estado_primer_pago: 'Estado del primer pago', tipo_credito_legal: 'Tipo crédito legal',
};
const FILTROS_PRINCIPALES = ['sucursal', 'canal', 'producto_comercial', 'clasificacion', 'rango_score', 'promotor'];
const FILTROS_MAS = ['categorizacion', 'tipo_credito', 'sucursal_promotor', 'medio_captacion', 'rango_desembolso',
  'rango_salario', 'rango_edad', 'rango_multiplicador', 'rango_antig_cliente', 'rango_antig_credito', 'rango_antig_laboral',
  'rango_capacidad', 'rango_ingreso', 'rango_estabilidad', 'perfil_motor', 'politica_hit', 'producto_motor', 'plazo',
  'genero', 'empleo_inss'];
const FILTROS_COBRO = ['mora', 'rodamiento', 'tipo_cartera', 'tipo_pago', 'pago_mes', 'gestor', 'tipo_credito_legal'];
const DIMS_VER_POR = ['sucursal', 'canal', 'producto_comercial', 'promotor', 'sucursal_promotor', 'clasificacion',
  'categorizacion', 'rango_score', 'rango_desembolso', 'rango_salario', 'rango_edad', 'rango_capacidad', 'rango_ingreso',
  'rango_antig_cliente', 'rango_antig_laboral', 'rango_multiplicador', 'perfil_motor', 'medio_captacion', 'plazo',
  'tipo_credito', 'mes_desembolso', 'empleo_inss'];
const CONO_DIMS = { tipo_cartera: 'Tipo de cartera', usuario: 'Gestor', descripcion_accion: 'Acción', descripcion_resultado: 'Resultado', de_la_cosecha: 'Crédito de la cosecha' };

const S = { perfil: null, tab: null, datos: {}, meta: null, f: {}, cono: {}, verPor: {}, tablaPor: {}, charts: {}, mas: false };

// ---------- Formatos ----------
const nf = new Intl.NumberFormat('es-NI', { maximumFractionDigits: 0 });
const fN = v => nf.format(v || 0);
const fP = v => (v == null || !isFinite(v) ? '—' : `${v.toLocaleString('es-NI', { maximumFractionDigits: 1, minimumFractionDigits: 1 })}%`);
const fM = v => {
  const a = Math.abs(v || 0);
  if (a >= 1e6) return `C$ ${(v / 1e6).toLocaleString('es-NI', { maximumFractionDigits: 1 })} M`;
  if (a >= 1e3) return `C$ ${(v / 1e3).toLocaleString('es-NI', { maximumFractionDigits: 0 })} mil`;
  return `C$ ${fN(v)}`;
};
const pct = (a, b) => (b ? (100 * a) / b : null);
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const fMes = p => { const [a, m] = String(p).split('-'); return m ? `${MESES[+m - 1]} ${a.slice(2)}` : p; };
const fDia = d => { const [, m, dd] = String(d).split('-'); return dd ? `${+dd} ${MESES[+m - 1]}` : d; };

// ---------- Sesión ----------
async function perfilActual() {
  const { data } = await sb.auth.getSession();
  if (!data.session) return null;
  return ok(await sb.from('cvc_perfiles').select('*').eq('id', data.session.user.id).maybeSingle());
}

function mostrarLogin(msg = '') {
  $('app').hidden = true; $('login').hidden = false; $('flog').hidden = false; $('fclave').hidden = true;
  $('lmsg').textContent = msg;
}

$('flog').addEventListener('submit', async e => {
  e.preventDefault();
  const clave = $('lp').value;
  try {
    ok(await sb.auth.signInWithPassword({ email: slug($('lu').value) + DOMINIO, password: clave }));
    const p = await perfilActual();
    if (!p || !p.activo) { await sb.auth.signOut(); return mostrarLogin('Usuario sin acceso a Cosechas vs Cobro'); }
    S.perfil = p; $('lp').value = '';
  } catch { return mostrarLogin('Usuario o contraseña incorrectos'); }
  if (clave === CLAVE_INICIAL) {
    $('flog').hidden = true; $('fclave').hidden = false; $('cmsg').textContent = '';
    return $('cn1').focus();
  }
  await iniciar();
});

$('fclave').addEventListener('submit', async e => {
  e.preventDefault();
  const n1 = $('cn1').value, n2 = $('cn2').value;
  if (n1.length < 8) return ($('cmsg').textContent = 'La contraseña debe tener al menos 8 caracteres.');
  if (n1 === CLAVE_INICIAL) return ($('cmsg').textContent = 'Use una contraseña distinta de la genérica.');
  if (n1 !== n2) return ($('cmsg').textContent = 'Las dos contraseñas no coinciden.');
  try { ok(await sb.auth.updateUser({ password: n1 })); $('cn1').value = $('cn2').value = ''; await iniciar(); }
  catch (err) { $('cmsg').textContent = err.message; }
});

const rol = () => S.perfil?.rol;
const puedeDescargar = () => ['admin', 'gerencia'].includes(rol());
const veTablas = () => rol() !== 'gerencia';   // gerencia: solo gráficos

async function iniciar() {
  $('login').hidden = true; $('app').hidden = false;
  $('yoNombre').textContent = S.perfil.nombre;
  $('yoRol').textContent = ROLES[rol()] || '';
  $('btnClave').hidden = $('btnSalir').hidden = LOCAL;
  $('btnDescargar').hidden = !puedeDescargar();
  const mias = PESTANAS.filter(p => p.roles.includes(rol()));
  $('tabs').innerHTML = mias.map(p => `<button data-tab="${p.id}">${p.t}</button>`).join('')
    + (rol() === 'admin' ? '<button data-tab="admin">Administración</button>' : '');
  sugerencias();
  await leerMeta();
  const pedida = QS.get('tab');
  await abrir(mias.some(p => p.id === pedida) ? pedida : mias[0]?.id || 'admin');
}

// ---------- Datos ----------
async function leerMeta() {
  try {
    S.meta = LOCAL ? await (await fetch('local/meta.json', { cache: 'no-store' })).json()
      : ok(await sb.from('cvc_config').select('valor').eq('clave', 'ultima_carga'))[0]?.valor;
  } catch { S.meta = null; }
  const u = S.meta?.ultima_actualizacion;
  $('ultima').textContent = u ? `Actualizado ${new Date(u).toLocaleString('es-NI', { dateStyle: 'medium', timeStyle: 'short' })}` : 'Sin datos aún';
}

async function bajar(tab) {
  if (S.datos[tab]) return S.datos[tab];
  let d;
  if (LOCAL) d = await (await fetch(`local/${tab}.json`, { cache: 'no-store' })).json();
  else {
    const blob = ok(await sb.storage.from(CFG.BUCKET).download(`pestanas/${tab}.json.gz`));
    const txt = await new Response(blob.stream().pipeThrough(new DecompressionStream('gzip'))).text();
    d = JSON.parse(txt);
  }
  S.datos[tab] = d;
  return d;
}

// Valor de una fila: dimensión → texto del diccionario; medida → número
const dv = (D, c, i) => { const k = D.datos[c]?.[i]; return k == null ? null : D.dic[c] ? D.dic[c][k] : k; };
const mv = (D, c, i) => D.datos[c]?.[i] || 0;

// Filas que pasan los filtros actuales
function filas(D, filtros, desde, hasta) {
  const conds = [];
  for (const [c, v] of Object.entries(filtros)) {
    if (!v || !D.dic[c]) continue;
    const k = D.dic[c].indexOf(v);
    conds.push([D.datos[c], k]);
  }
  let mesOk = null;
  if ((desde || hasta) && D.dic.mes_desembolso) {
    mesOk = new Set(D.dic.mes_desembolso.map((m, k) => ((!desde || m >= desde) && (!hasta || m <= hasta) ? k : -1)).filter(k => k >= 0));
  }
  const out = [];
  for (let i = 0; i < D.n; i++) {
    let pasa = true;
    for (const [col, k] of conds) if (col[i] !== k) { pasa = false; break; }
    if (pasa && mesOk && !mesOk.has(D.datos.mes_desembolso[i])) pasa = false;
    if (pasa) out.push(i);
  }
  return out;
}

// Agrupa índices por una dimensión con un acumulador
function agrupar(D, idx, dim, nuevo, sumar) {
  const m = new Map();
  for (const i of idx) {
    const k = dim ? (dv(D, dim, i) ?? 'SIN DATO') : 'Total';
    let a = m.get(k);
    if (!a) m.set(k, (a = nuevo()));
    sumar(a, i);
  }
  return m;
}

// ---------- Indicadores de crédito ----------
const accCred = D => [() => ({ n: 0, monto: 0, act: 0, saldo: 0, b0: 0, m30: 0, m90: 0, s30: 0, desm: 0, pagoMes: 0, grupos: [0, 0, 0, 0, 0, 0], sgrupos: [0, 0, 0, 0, 0, 0] }),
  (a, i) => {
    const mora = dv(D, 'mora', i), s = mv(D, 'saldo_doc', i), g = MORA_A_GRUPO[mora] ?? 5;
    a.n++; a.monto += mv(D, 'monto_des', i); a.grupos[g]++; a.sgrupos[g] += s;
    if (mora !== 'CANCELADO') { a.act++; a.saldo += s; }
    if (mora === 'B0') a.b0++;
    if (M30.has(mora)) { a.m30++; a.s30 += s; }
    if (M90.has(mora)) a.m90++;
    if (dv(D, 'rodamiento', i) === 'DESMEJORA') a.desm++;
    const pm = dv(D, 'pago_mes', i);
    if (pm && pm !== 'Sin pago este mes') a.pagoMes++;
  }];
const accPP = D => [() => ({ n: 0, venc: 0, pago: 0, mora: 0, sinpago: 0, porvencer: 0, canc: 0 }),
  (a, i) => {
    const e = dv(D, 'estado_primer_pago', i);
    a.n++;
    if (e === 'Pagó') a.pago++; else if (e === 'En mora') a.mora++; else if (e === 'Vencida sin pago registrado') a.sinpago++;
    else if (e === 'Por vencer') a.porvencer++; else if (e === 'Cancelado') a.canc++;
    if (e !== 'Por vencer') a.venc++;
  }];

// ---------- Filtros ----------
function opciones(D, c) { return D.dic[c] ? [...D.dic[c]].sort((a, b) => a.localeCompare(b, 'es', { numeric: true })) : []; }

function pintarFiltros(D) {
  const cono = S.tab === 'cono';
  const sel = (c, t, vals, actual) => `<label class="${actual ? 'activo' : ''}">${t}<select data-f="${c}"><option value="">Todos</option>${vals.map(v => `<option${v === actual ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`;
  if (cono) {
    const G = D.gestiones;
    const dias = G.dic.dia.slice().sort();
    $('filtros').innerHTML = `<label>Desde<select data-c="desde"><option value="">Inicio del mes</option>${dias.map(d => `<option value="${d}"${d === S.cono.desde ? ' selected' : ''}>${fDia(d)}</option>`).join('')}</select></label>`
      + `<label>Hasta<select data-c="hasta"><option value="">Hoy</option>${dias.map(d => `<option value="${d}"${d === S.cono.hasta ? ' selected' : ''}>${fDia(d)}</option>`).join('')}</select></label>`
      + Object.entries(CONO_DIMS).map(([c, t]) => sel(c, t, opciones(G, c), S.cono[c]).replace('data-f=', 'data-c=')).join('')
      + '<div class="acciones-f"><button type="button" class="btn lin mini" id="limpiar">Limpiar filtros</button></div>';
    $('filtrosMas').hidden = true;
    return;
  }
  const meses = (D.dic.mes_desembolso || []).slice().sort();
  const mesSel = (k, t, vacio) => `<label class="${S.f[k] ? 'activo' : ''}">${t}<select data-f="${k}"><option value="">${vacio}</option>${meses.map(m => `<option value="${m}"${m === S.f[k] ? ' selected' : ''}>${fMes(m)}</option>`).join('')}</select></label>`;
  const extra = S.tab === 'cartera_activa' || S.tab === 'primeros_pagos' ? FILTROS_COBRO.filter(c => D.dic[c]) : [];
  $('filtros').innerHTML = (S.tab === 'primeros_pagos' ? '' : mesSel('_desde', 'Cosecha desde', 'Primera') + mesSel('_hasta', 'Cosecha hasta', 'Última'))
    + FILTROS_PRINCIPALES.filter(c => D.dic[c]).map(c => c === 'promotor'
      ? `<label class="${S.f.promotor ? 'activo' : ''}">Promotor<input list="lpromotor" data-f="promotor" value="${esc(S.f.promotor || '')}" placeholder="Todos"><datalist id="lpromotor">${opciones(D, 'promotor').map(v => `<option value="${esc(v)}">`).join('')}</datalist></label>`
      : sel(c, DIM[c], opciones(D, c), S.f[c])).join('')
    + `<div class="acciones-f"><button type="button" class="btn lin mini" id="verMas">${S.mas ? 'Menos filtros' : 'Más filtros'}</button><button type="button" class="btn lin mini" id="limpiar">Limpiar filtros</button></div>`;
  $('filtrosMas').hidden = !S.mas;
  $('filtrosMas').innerHTML = [...extra, ...FILTROS_MAS].filter(c => D.dic[c]).map(c => sel(c, DIM[c], opciones(D, c), S.f[c])).join('');
}

function filtrosActivos() {
  const f = {};
  for (const [k, v] of Object.entries(S.f)) if (v && !k.startsWith('_')) f[k] = v;
  return f;
}

document.addEventListener('change', e => {
  const t = e.target;
  if (t.dataset.f !== undefined) { S.f[t.dataset.f] = t.value; pintar(); }
  else if (t.dataset.c !== undefined) { S.cono[t.dataset.c] = t.value; pintar(); }
  else if (t.dataset.verpor !== undefined) { S.verPor[t.dataset.verpor] = t.value; pintar(); }
});
document.addEventListener('click', e => {
  if (e.target.id === 'limpiar') { if (S.tab === 'cono') S.cono = {}; else S.f = {}; pintar(); }
  if (e.target.id === 'verMas') { S.mas = !S.mas; pintar(); }
});

// ---------- Gráficos ----------
Chart.defaults.font.family = 'Arial, Helvetica, sans-serif';
Chart.defaults.font.size = 12;
Chart.defaults.color = '#5B6170';
Chart.defaults.animation.duration = 0;   // al filtrar, los gráficos cambian al instante

// Etiqueta de valor en la punta de cada barra (para barras simples)
const pluginEtiquetas = {
  id: 'etiquetas',
  afterDatasetsDraw(chart) {
    const o = chart.options.plugins.etiquetas;
    if (!o?.mostrar) return;
    const { ctx } = chart;
    ctx.save();
    ctx.font = '12px Arial'; ctx.fillStyle = '#333740';
    chart.data.datasets.forEach((ds, di) => {
      chart.getDatasetMeta(di).data.forEach((el, i) => {
        const v = ds.data[i];
        if (v == null) return;
        const t = ds.fmtEtiqueta ? ds.fmtEtiqueta(v) : fN(v);
        if (chart.options.indexAxis === 'y') { ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(t, el.x + 6, el.y); }
        else { ctx.textAlign = 'center'; ctx.textBaseline = 'bottom'; ctx.fillText(t, el.x, el.y - 4); }
      });
    });
    ctx.restore();
  },
};
Chart.register(pluginEtiquetas);

function tarjeta(id, titulo, nota, { ancho = false, alto = false, verPor = null, leyenda = null } = {}) {
  const sel = verPor ? `<label class="small">Ver por <select data-verpor="${id}">${DIMS_VER_POR.filter(d => verPor.D.dic[d]).map(d => `<option value="${d}"${d === verPor.valor ? ' selected' : ''}>${DIM[d]}</option>`).join('')}</select></label>` : '';
  const ley = leyenda ? `<div class="leyenda">${leyenda.map(([t, c]) => `<span><i style="background:${c}"></i>${esc(t)}</span>`).join('')}</div>` : '';
  return `<article class="graf${ancho ? ' ancho' : ''}${alto ? ' alto' : ''}"><div class="cab"><h3>${titulo}</h3>${sel}</div>${nota ? `<p class="nota">${nota}</p>` : ''}${ley}<div class="lienzo"><canvas id="${id}"></canvas></div></article>`;
}

function grafico(id, cfg) {
  S.charts[id]?.destroy();
  const el = $(id);
  if (!el) return;
  S.charts[id] = new Chart(el, cfg);
}

function ejes({ horizontal = false, apilado = false, fmtValor = fN, max = undefined } = {}) {
  const valor = { stacked: apilado, beginAtZero: true, max, grid: { color: '#E6E8EC' }, border: { display: false }, ticks: { callback: v => fmtValor(v), maxTicksLimit: 6 } };
  const cat = { stacked: apilado, grid: { display: false }, border: { color: '#C3C7CF' }, ticks: { autoSkip: !horizontal, maxRotation: 0 } };
  return horizontal ? { x: valor, y: cat } : { x: cat, y: valor };
}

function tooltipCfg(fmt, extra) {
  return {
    backgroundColor: '#fff', titleColor: '#06255B', bodyColor: '#333740', borderColor: '#D9DDE4', borderWidth: 1, padding: 10,
    titleFont: { weight: 'bold' }, bodyFont: { size: 12 }, usePointStyle: true, boxWidth: 8, boxHeight: 2,
    callbacks: { label: c => `${fmt(c.raw, c)}  ${c.dataset.label || ''}`, afterBody: extra },
  };
}

// Barras simples (una serie): horizontal para rankings por dimensión, vertical para categorías ordenadas
function barrasSimples(id, etiquetas, valores, { color = SERIE[1], horizontal = true, fmt = fN, extra = null, max } = {}) {
  grafico(id, {
    type: 'bar',
    data: { labels: etiquetas, datasets: [{ data: valores, fmtEtiqueta: fmt, backgroundColor: color, borderRadius: 4, borderSkipped: 'start', maxBarThickness: 24, categoryPercentage: 0.8 }] },
    options: {
      indexAxis: horizontal ? 'y' : 'x', responsive: true, maintainAspectRatio: false,
      layout: { padding: { right: horizontal ? 60 : 0, top: horizontal ? 0 : 18 } },
      scales: ejes({ horizontal, fmtValor: fmt, max }),
      plugins: { legend: { display: false }, tooltip: tooltipCfg(fmt, extra), etiquetas: { mostrar: true } },
    },
  });
}

// Barras apiladas (varias series de la misma unidad)
function barrasApiladas(id, etiquetas, series, { horizontal = false, fmt = fN, cien = false, extra = null } = {}) {
  grafico(id, {
    type: 'bar',
    data: { labels: etiquetas, datasets: series.map(s => ({ label: s.t, data: s.v, backgroundColor: s.c, borderColor: '#fff', borderWidth: horizontal ? { right: 2 } : { top: 2 }, borderSkipped: false, maxBarThickness: 28, categoryPercentage: 0.8 })) },
    options: {
      indexAxis: horizontal ? 'y' : 'x', responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      scales: ejes({ horizontal, apilado: true, fmtValor: cien ? v => `${v}%` : fmt, max: cien ? 100 : undefined }),
      plugins: { legend: { display: false }, tooltip: tooltipCfg(cien ? v => fP(v) : fmt, extra) },
    },
  });
}

// Líneas (misma unidad, un solo eje)
function lineas(id, etiquetas, series, { fmt = fN } = {}) {
  grafico(id, {
    type: 'line',
    data: { labels: etiquetas, datasets: series.map(s => ({ label: s.t, data: s.v, borderColor: s.c, backgroundColor: s.c, borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, pointBorderColor: '#fff', pointBorderWidth: 2, tension: 0.25, spanGaps: true })) },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      scales: ejes({ fmtValor: fmt }),
      plugins: { legend: { display: false }, tooltip: tooltipCfg(fmt) },
    },
  });
}

// Barras agrupadas (dos series de la misma unidad)
function barrasAgrupadas(id, etiquetas, series, { fmt = fN } = {}) {
  grafico(id, {
    type: 'bar',
    data: { labels: etiquetas, datasets: series.map(s => ({ label: s.t, data: s.v, backgroundColor: s.c, borderRadius: 4, borderSkipped: 'start', maxBarThickness: 20, categoryPercentage: 0.75, barPercentage: 0.9 })) },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      scales: ejes({ fmtValor: fmt }), plugins: { legend: { display: false }, tooltip: tooltipCfg(fmt) },
    },
  });
}

function kpis(lista) {
  $('kpis').innerHTML = lista.map(([l, v, s, c]) => `<div class="kpi ${c}"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s || ''}</div></div>`).join('');
}

// Ranking por dimensión: los grupos con más créditos (los pequeños distorsionan los porcentajes)
function ranking(m, { top = 15, minimo = 1, valor, orden }) {
  return [...m.entries()].filter(([, a]) => a.n >= minimo).sort((x, y) => orden(y[1]) - orden(x[1])).slice(0, top)
    .map(([k, a]) => [k, valor(a), a]);
}

// ---------- Tabla por dimensión ----------
function tabla(titulo, opcionesPor, por, columnas, m, total) {
  const caja = $('tablaCaja');
  caja.hidden = !veTablas();
  if (caja.hidden) return;
  $('tablaTit').textContent = titulo;
  $('tablaPor').innerHTML = opcionesPor.map(([d, t]) => `<option value="${d}"${d === por ? ' selected' : ''}>${t}</option>`).join('');
  $('tablaPor').dataset.verpor = `tabla_${S.tab}`;
  $('thead').innerHTML = `<tr><th>${esc((opcionesPor.find(o => o[0] === por) || [, ''])[1])}</th>${columnas.map(c => `<th class="num">${c.t}</th>`).join('')}</tr>`;
  const filasT = [...m.entries()].sort((a, b) => (por === 'mes_desembolso' || por === 'dia' ? String(b[0]).localeCompare(String(a[0])) : b[1].n - a[1].n));
  const celda = (c, a) => { const v = c.v(a); return `<td class="num${c.alerta && c.alerta(a) ? ' alerta' : ''}">${c.f(v)}</td>`; };
  $('tbody').innerHTML = filasT.map(([k, a]) => `<tr><td>${esc(por === 'mes_desembolso' ? fMes(k) : k)}</td>${columnas.map(c => celda(c, a)).join('')}</tr>`).join('')
    + (total ? `<tr class="total"><td>Total</td>${columnas.map(c => celda(c, total)).join('')}</tr>` : '');
}

// ---------- Pestaña Cosecha ----------
function pintarCosecha(D) {
  const idx = filas(D, filtrosActivos(), S.f._desde, S.f._hasta);
  const [n0, sm] = accCred(D);
  const tot = agrupar(D, idx, null, n0, sm).get('Total') || n0();
  kpis([
    ['Créditos desembolsados', fN(tot.n), fM(tot.monto), 'navy'],
    ['Al día hoy', fP(pct(tot.b0, tot.n)), `${fN(tot.b0)} créditos`, ''],
    ['Mora 30+', fP(pct(tot.m30, tot.n)), `${fN(tot.m30)} créditos · ${fM(tot.s30)}`, 'naranja'],
    ['Mora 90+', fP(pct(tot.m90, tot.n)), `${fN(tot.m90)} créditos`, 'rojo'],
    ['Cancelados', fP(pct(tot.n - tot.act, tot.n)), `${fN(tot.n - tot.act)} créditos`, 'cielo'],
    ['Saldo activo', fM(tot.saldo), `${fN(tot.act)} créditos activos`, 'lima'],
  ]);
  const vp = S.verPor.cosecha_dim || 'sucursal';
  $('graficos').innerHTML =
    tarjeta('gCosechaMora', 'Cómo está hoy cada cosecha', 'Distribución de los créditos de cada mes de desembolso según su tramo de mora actual.', { ancho: true, leyenda: MORA_GRUPOS.map((t, i) => [t, MORA_COLOR[i]]) })
    + tarjeta('gCosechaPct', 'Mora 30+ y 90+ por cosecha', 'Porcentaje de los créditos desembolsados en cada mes que hoy tienen más de 30 o más de 90 días de mora.', { leyenda: [['Mora 30+', SERIE[2]], ['Mora 90+', SERIE[1]]] })
    + tarjeta('gCosechaVol', 'Créditos desembolsados por mes', 'Nuevos y renovaciones.', { leyenda: [['Nuevo', SERIE[0]], ['Renovación', SERIE[1]]] })
    + tarjeta('gCosechaDim', 'Mora 30+ por grupo', 'Los 15 grupos con más créditos (mínimo 30), ordenados por porcentaje de mora 30+.', { ancho: true, alto: true, verPor: { id: 'cosecha_dim', D, valor: vp } });
  const porMes = agrupar(D, idx, 'mes_desembolso', n0, sm);
  const meses = [...porMes.keys()].sort();
  barrasApiladas('gCosechaMora', meses.map(fMes), MORA_GRUPOS.map((t, g) => ({ t, c: MORA_COLOR[g], v: meses.map(m => pct(porMes.get(m).grupos[g], porMes.get(m).n)) })),
    { cien: true, extra: items => `${fN(porMes.get(meses[items[0].dataIndex]).n)} créditos en la cosecha` });
  lineas('gCosechaPct', meses.map(fMes), [
    { t: 'Mora 30+', c: SERIE[2], v: meses.map(m => pct(porMes.get(m).m30, porMes.get(m).n)) },
    { t: 'Mora 90+', c: SERIE[1], v: meses.map(m => pct(porMes.get(m).m90, porMes.get(m).n)) },
  ], { fmt: fP });
  const clas = agrupar(D, idx, 'mes_desembolso', () => ({ NUEVO: 0, RENOVACION: 0 }), (a, i) => { a[dv(D, 'clasificacion', i)]++; });
  barrasApiladas('gCosechaVol', meses.map(fMes), [
    { t: 'Nuevo', c: SERIE[0], v: meses.map(m => clas.get(m).NUEVO) },
    { t: 'Renovación', c: SERIE[1], v: meses.map(m => clas.get(m).RENOVACION) },
  ]);
  const r = ranking(agrupar(D, idx, vp, n0, sm), { minimo: 30, valor: a => pct(a.m30, a.n), orden: a => a.n }).sort((a, b) => b[1] - a[1]);
  barrasSimples('gCosechaDim', r.map(x => vp === 'mes_desembolso' ? fMes(x[0]) : x[0]), r.map(x => x[1]),
    { color: SERIE[2], fmt: fP, extra: it => `${fN(r[it[0].dataIndex][2].n)} créditos · ${fN(r[it[0].dataIndex][2].m30)} en mora 30+` });
  const tp = S.verPor.tabla_cosecha || 'sucursal';
  const mt = agrupar(D, idx, tp, n0, sm);
  tabla('Detalle de la cosecha', DIMS_VER_POR.filter(d => D.dic[d]).map(d => [d, DIM[d]]), tp, [
    { t: 'Créditos', v: a => a.n, f: fN }, { t: 'Monto desembolsado', v: a => a.monto, f: fM },
    { t: 'Activos', v: a => a.act, f: fN }, { t: 'Saldo', v: a => a.saldo, f: fM },
    { t: '% al día', v: a => pct(a.b0, a.n), f: fP }, { t: '% mora 30+', v: a => pct(a.m30, a.n), f: fP, alerta: a => pct(a.m30, a.n) > pct(tot.m30, tot.n) * 1.25 },
    { t: '% mora 90+', v: a => pct(a.m90, a.n), f: fP }, { t: '% cancelado', v: a => pct(a.n - a.act, a.n), f: fP },
  ], mt, tot);
}

// ---------- Pestaña Cartera Activa ----------
function pintarCartera(D) {
  const idx = filas(D, filtrosActivos(), S.f._desde, S.f._hasta);
  const [n0, sm] = accCred(D);
  const tot = agrupar(D, idx, null, n0, sm).get('Total') || n0();
  kpis([
    ['Créditos activos', fN(tot.act), 'en la cartera de cobro hoy', 'navy'],
    ['Saldo', fM(tot.saldo), 'saldo de los créditos activos', ''],
    ['Al día', fP(pct(tot.b0, tot.act)), `${fN(tot.b0)} créditos`, 'lima'],
    ['Saldo en mora 30+', fM(tot.s30), `${fP(pct(tot.s30, tot.saldo))} del saldo`, 'naranja'],
    ['Rodamiento: desmejora', fP(pct(tot.desm, tot.act)), `${fN(tot.desm)} créditos`, 'rojo'],
    ['Pagaron este mes', fP(pct(tot.pagoMes, tot.act)), `${fN(tot.pagoMes)} créditos`, 'cielo'],
  ]);
  const vp = S.verPor.cartera_dim || 'sucursal';
  $('graficos').innerHTML =
    tarjeta('gCarMora', 'Saldo por tramo de mora', 'Saldo de la cartera activa según días de mora hoy.', {})
    + tarjeta('gCarRod', 'Rodamiento (Cendoc)', 'Cómo se movió cada crédito respecto al corte anterior.', {})
    + tarjeta('gCarPago', 'Pago en el mes', 'Último pago del mes comparado con el día de pago del crédito.', {})
    + tarjeta('gCarTipo', 'Tipo del último pago', 'Último pago registrado comparado con el valor de la cuota.', {})
    + tarjeta('gCarDim', '% del saldo en mora 30+ por grupo', 'Los 15 grupos con más créditos activos (mínimo 20).', { ancho: true, alto: true, verPor: { id: 'cartera_dim', D, valor: vp } });
  barrasSimples('gCarMora', MORA_GRUPOS.slice(0, 5), tot.sgrupos.slice(0, 5), { horizontal: false, fmt: fM, color: MORA_COLOR.slice(0, 5), extra: it => `${fN(tot.grupos[it[0].dataIndex])} créditos` });
  const cuenta = dim => { const m = agrupar(D, idx, dim, () => ({ n: 0, s: 0 }), (a, i) => { a.n++; a.s += mv(D, 'saldo_doc', i); }); return [...m.entries()].sort((a, b) => b[1].n - a[1].n); };
  const rod = cuenta('rodamiento');
  barrasSimples('gCarRod', rod.map(x => x[0]), rod.map(x => x[1].n), { color: SERIE[1], extra: it => fM(rod[it[0].dataIndex][1].s) });
  const pm = cuenta('pago_mes');
  barrasSimples('gCarPago', pm.map(x => x[0]), pm.map(x => x[1].n), { color: SERIE[0], extra: it => fP(pct(pm[it[0].dataIndex][1].n, tot.act)) + ' de los activos' });
  const tpg = cuenta('tipo_pago');
  barrasSimples('gCarTipo', tpg.map(x => x[0]), tpg.map(x => x[1].n), { color: SERIE[3], extra: it => fP(pct(tpg[it[0].dataIndex][1].n, tot.act)) + ' de los activos' });
  const r = ranking(agrupar(D, idx, vp, n0, sm), { minimo: 20, valor: a => pct(a.s30, a.saldo), orden: a => a.n }).sort((a, b) => b[1] - a[1]);
  barrasSimples('gCarDim', r.map(x => vp === 'mes_desembolso' ? fMes(x[0]) : x[0]), r.map(x => x[1]),
    { color: SERIE[2], fmt: fP, extra: it => `${fN(r[it[0].dataIndex][2].act)} activos · saldo 30+ ${fM(r[it[0].dataIndex][2].s30)}` });
  const tp = S.verPor.tabla_cartera_activa || 'sucursal';
  tabla('Detalle de la cartera activa', [...DIMS_VER_POR, 'mora', 'rodamiento', 'tipo_cartera', 'gestor', 'tipo_pago', 'pago_mes'].filter(d => D.dic[d]).map(d => [d, DIM[d]]), tp, [
    { t: 'Créditos', v: a => a.act, f: fN }, { t: 'Saldo', v: a => a.saldo, f: fM },
    { t: '% al día', v: a => pct(a.b0, a.act), f: fP }, { t: 'Saldo mora 30+', v: a => a.s30, f: fM },
    { t: '% saldo 30+', v: a => pct(a.s30, a.saldo), f: fP, alerta: a => pct(a.s30, a.saldo) > pct(tot.s30, tot.saldo) * 1.25 },
    { t: '% desmejora', v: a => pct(a.desm, a.act), f: fP }, { t: '% pagaron este mes', v: a => pct(a.pagoMes, a.act), f: fP },
  ], agrupar(D, idx, tp, n0, sm), tot);
}

// ---------- Pestaña Primeros Pagos ----------
const PP_ESTADOS = [['Pagó', 'pago', SERIE[0]], ['Por vencer', 'porvencer', SERIE[1]], ['En mora', 'mora', SERIE[2]],
  ['Vencida sin pago registrado', 'sinpago', SERIE[3]], ['Cancelado', 'canc', GRIS]];

function pintarPrimeros(D) {
  const idx = filas(D, filtrosActivos());
  const [n0, sm] = accPP(D);
  const tot = agrupar(D, idx, null, n0, sm).get('Total') || n0();
  const hoy = new Date();
  kpis([
    ['Primera cuota este mes', fN(tot.n), `${MESES[hoy.getMonth()]} ${hoy.getFullYear()}`, 'navy'],
    ['Ya vencieron', fN(tot.venc), fP(pct(tot.venc, tot.n)) + ' del total', 'cielo'],
    ['Pagaron', fN(tot.pago), fP(pct(tot.pago, tot.venc)) + ' de los vencidos', ''],
    ['En mora', fN(tot.mora), fP(pct(tot.mora, tot.venc)) + ' de los vencidos', 'naranja'],
    ['Vencida sin pago registrado', fN(tot.sinpago), fP(pct(tot.sinpago, tot.venc)) + ' de los vencidos', 'amarillo'],
    ['Por vencer', fN(tot.porvencer), 'aún no llega la fecha', 'lima'],
  ]);
  const vp = S.verPor.pp_dim || 'sucursal';
  $('graficos').innerHTML =
    tarjeta('gPPDia', 'Primeros pagos por fecha de vencimiento', 'Créditos según el día en que vence su primera cuota y cómo están hoy.', { ancho: true, leyenda: PP_ESTADOS.map(e => [e[0], e[2]]) })
    + tarjeta('gPPDim', '% en mora sobre los vencidos', 'Los 15 grupos con más créditos vencidos (mínimo 5).', { ancho: true, alto: true, verPor: { id: 'pp_dim', D, valor: vp } });
  const porDia = agrupar(D, idx, 'primera_cuota', n0, sm);
  const dias = [...porDia.keys()].sort();
  barrasApiladas('gPPDia', dias.map(fDia), PP_ESTADOS.map(([t, k, c]) => ({ t, c, v: dias.map(d => porDia.get(d)[k]) })));
  const r = [...agrupar(D, idx, vp, n0, sm).entries()].filter(([, a]) => a.venc >= 5).sort((a, b) => b[1].venc - a[1].venc).slice(0, 15)
    .map(([k, a]) => [k, pct(a.mora, a.venc), a]).sort((a, b) => b[1] - a[1]);
  barrasSimples('gPPDim', r.map(x => vp === 'mes_desembolso' ? fMes(x[0]) : x[0]), r.map(x => x[1]),
    { color: SERIE[2], fmt: fP, extra: it => `${fN(r[it[0].dataIndex][2].venc)} vencidos · ${fN(r[it[0].dataIndex][2].mora)} en mora` });
  const tp = S.verPor.tabla_primeros_pagos || 'promotor';
  tabla('Detalle de primeros pagos', DIMS_VER_POR.filter(d => D.dic[d]).map(d => [d, DIM[d]]), tp, [
    { t: 'Créditos', v: a => a.n, f: fN }, { t: 'Vencidos', v: a => a.venc, f: fN }, { t: 'Pagaron', v: a => a.pago, f: fN },
    { t: 'En mora', v: a => a.mora, f: fN }, { t: 'Sin pago registrado', v: a => a.sinpago, f: fN }, { t: 'Por vencer', v: a => a.porvencer, f: fN },
    { t: '% mora s/ vencidos', v: a => pct(a.mora, a.venc), f: fP, alerta: a => a.venc >= 5 && pct(a.mora, a.venc) > pct(tot.mora, tot.venc) * 1.5 },
  ], agrupar(D, idx, tp, n0, sm), tot);
}

// ---------- Pestaña Cono de cobranza ----------
function filasCono(T) {
  const f = {};
  for (const c of Object.keys(CONO_DIMS)) if (S.cono[c]) f[c] = S.cono[c];
  const idx = filas(T, f);
  const fecha = T.dic.dia ? 'dia' : 'fecha_promesa';
  if (fecha === 'dia' && (S.cono.desde || S.cono.hasta)) {
    return idx.filter(i => { const d = dv(T, 'dia', i); return (!S.cono.desde || d >= S.cono.desde) && (!S.cono.hasta || d <= S.cono.hasta); });
  }
  return idx;
}

function pintarCono(D) {
  const G = D.gestiones, P = D.promesas;
  const ig = filasCono(G);
  const fP_ = {}; for (const c of ['tipo_cartera', 'usuario']) if (S.cono[c]) fP_[c] = S.cono[c];
  const ip = filas(P, fP_);
  const nuevo = () => ({ n: 0, gestionada: 0, contacto: 0, rpc: 0, promesa: 0 });
  const suma = (a, i) => { a.n += mv(G, 'n', i); for (const k of ['gestionada', 'contacto', 'rpc', 'promesa']) a[k] += mv(G, k, i); };
  const tot = agrupar(G, ig, null, nuevo, suma).get('Total') || nuevo();
  const pr = agrupar(P, ip, 'estado_promesa', () => ({ n: 0, prom: 0, pag: 0 }), (a, i) => { a.n += mv(P, 'n', i); a.prom += mv(P, 'monto_promesa', i); a.pag += mv(P, 'monto_pagado', i); });
  const cumpl = pr.get('Cumplida') || { n: 0, prom: 0, pag: 0 };
  const totP = [...pr.values()].reduce((s, a) => ({ n: s.n + a.n, prom: s.prom + a.prom, pag: s.pag + a.pag }), { n: 0, prom: 0, pag: 0 });
  kpis([
    ['Gestiones del mes', fN(tot.n), 'una por gestión (sin duplicados)', 'navy'],
    ['Contactos', fN(tot.contacto), fP(pct(tot.contacto, tot.n)) + ' de las gestiones', 'cielo'],
    ['RPC', fN(tot.rpc), fP(pct(tot.rpc, tot.n)) + ' de las gestiones', ''],
    ['Promesas', fN(tot.promesa), fP(pct(tot.promesa, tot.rpc)) + ' de los RPC', 'naranja'],
    ['Promesas cumplidas', fN(cumpl.n), fP(pct(cumpl.n, totP.n)) + ' de las promesas', 'lima'],
    ['Monto pagado en promesas', fM(totP.pag), `de ${fM(totP.prom)} prometido`, 'amarillo'],
  ]);
  $('graficos').innerHTML =
    `<article class="graf"><div class="cab"><h3>Embudo de cobranza</h3></div><p class="nota">Cada paso como porcentaje del anterior.</p><div class="embudo" id="embudo"></div></article>`
    + tarjeta('gConoDia', 'Gestiones por día', 'Gestiones, contactos y promesas de cada día del mes.', { leyenda: [['Gestiones', SERIE[1]], ['Contactos', SERIE[0]], ['Promesas', SERIE[2]]] })
    + tarjeta('gConoProm', 'Promesas por fecha comprometida', 'Monto prometido contra monto pagado.', { leyenda: [['Prometido', SERIE[1]], ['Pagado', SERIE[0]]] })
    + tarjeta('gConoRes', 'Resultados más frecuentes', 'Los 12 resultados de gestión con más registros.', { alto: true });
  const pasos = [['Gestiones', tot.n], ['Gestionadas', tot.gestionada], ['Contacto', tot.contacto], ['RPC', tot.rpc], ['Promesa', tot.promesa], ['Promesa cumplida', cumpl.n]];
  $('embudo').innerHTML = pasos.map(([t, v], k) => `<div class="paso"><span class="nom">${t}</span><div><div class="barra" style="width:${Math.max(0.5, pct(v, tot.n) || 0)}%"></div></div><span class="val"><b>${fN(v)}</b> ${k ? fP(pct(v, pasos[k - 1][1])) : ''}</span></div>`).join('');
  const pd = agrupar(G, ig, 'dia', nuevo, suma);
  const dias = [...pd.keys()].sort();
  lineas('gConoDia', dias.map(fDia), [
    { t: 'Gestiones', c: SERIE[1], v: dias.map(d => pd.get(d).n) },
    { t: 'Contactos', c: SERIE[0], v: dias.map(d => pd.get(d).contacto) },
    { t: 'Promesas', c: SERIE[2], v: dias.map(d => pd.get(d).promesa) },
  ]);
  const pf = agrupar(P, ip, 'fecha_promesa', () => ({ prom: 0, pag: 0 }), (a, i) => { a.prom += mv(P, 'monto_promesa', i); a.pag += mv(P, 'monto_pagado', i); });
  const fechas = [...pf.keys()].filter(f => f !== 'SIN FECHA').sort();
  barrasAgrupadas('gConoProm', fechas.map(fDia), [
    { t: 'Prometido', c: SERIE[1], v: fechas.map(f => pf.get(f).prom) },
    { t: 'Pagado', c: SERIE[0], v: fechas.map(f => pf.get(f).pag) },
  ], { fmt: fM });
  const res = [...agrupar(G, ig, 'descripcion_resultado', nuevo, suma).entries()].sort((a, b) => b[1].n - a[1].n).slice(0, 12);
  barrasSimples('gConoRes', res.map(x => x[0]), res.map(x => x[1].n), { color: SERIE[1], extra: it => fP(pct(res[it[0].dataIndex][1].n, tot.n)) + ' de las gestiones' });
  const tp = S.verPor.tabla_cono || 'usuario';
  tabla('Detalle del cono', [['usuario', 'Gestor'], ['descripcion_accion', 'Acción'], ['descripcion_resultado', 'Resultado'], ['tipo_cartera', 'Tipo de cartera'], ['dia', 'Día']], tp, [
    { t: 'Gestiones', v: a => a.n, f: fN }, { t: 'Gestionadas', v: a => a.gestionada, f: fN }, { t: 'Contactos', v: a => a.contacto, f: fN },
    { t: 'RPC', v: a => a.rpc, f: fN }, { t: 'Promesas', v: a => a.promesa, f: fN },
    { t: '% contacto', v: a => pct(a.contacto, a.n), f: fP }, { t: '% RPC', v: a => pct(a.rpc, a.n), f: fP }, { t: '% promesa s/ RPC', v: a => pct(a.promesa, a.rpc), f: fP },
  ], agrupar(G, ig, tp, nuevo, suma), tot);
}

// ---------- Navegación ----------
async function abrir(tab) {
  S.tab = tab;
  document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
  const admin = tab === 'admin';
  $('vistaDatos').hidden = admin; $('vistaAdmin').hidden = !admin;
  if (admin) return pintarUsuarios();
  $('cargando').hidden = false; $('vistaDatos').hidden = true;
  try { await bajar(tab); aviso(''); }
  catch (err) { aviso(`No se pudieron cargar los datos de esta pestaña: ${err.message}`, true); }
  finally { $('cargando').hidden = true; $('vistaDatos').hidden = false; }
  pintar();
}

function pintar() {
  const D = S.datos[S.tab];
  if (!D) { $('kpis').innerHTML = $('graficos').innerHTML = ''; $('tablaCaja').hidden = true; return; }
  pintarFiltros(D);
  ({ cosecha: pintarCosecha, cartera_activa: pintarCartera, primeros_pagos: pintarPrimeros, cono: pintarCono })[S.tab](D);
}

$('tabs').addEventListener('click', e => { const b = e.target.closest('button[data-tab]'); if (b) abrir(b.dataset.tab); });

// ---------- Descarga ----------
$('btnDescargar').addEventListener('click', async () => {
  try {
    if (LOCAL) { location.href = 'local/Base Cosechas vs Cobro.xlsx'; return; }
    const { signedUrl } = ok(await sb.storage.from(CFG.BUCKET).createSignedUrl('descargas/base.xlsx', 120, { download: 'Base Cosechas vs Cobro.xlsx' }));
    location.href = signedUrl;
  } catch (err) { aviso(`No se pudo descargar: ${err.message}`, true); }
});

// ---------- Actualizar ----------
function aviso(texto, error = false) {
  $('aviso').hidden = !texto; $('aviso').textContent = texto || ''; $('aviso').classList.toggle('error', error);
}

$('btnActualizar').addEventListener('click', async () => {
  if (LOCAL) { S.datos = {}; await leerMeta(); return abrir(S.tab); }
  const btn = $('btnActualizar');
  btn.disabled = true; btn.textContent = 'Actualizando…';
  try {
    const p = ok(await sb.from('cvc_actualizaciones').insert({ solicitado_nombre: S.perfil.nombre }).select().single());
    const t0 = Date.now();
    for (;;) {
      await new Promise(r => setTimeout(r, 5000));
      const e = ok(await sb.from('cvc_actualizaciones').select('estado,mensaje').eq('id', p.id).single());
      if (e.estado === 'ok') { aviso(''); S.datos = {}; await leerMeta(); await abrir(S.tab); break; }
      if (e.estado === 'error') { aviso(`La actualización falló: ${e.mensaje || ''}`, true); break; }
      if (e.estado === 'pendiente' && Date.now() - t0 > 60000) {
        aviso('El proceso de actualización no respondió: la PC que lo ejecuta puede estar apagada. Se muestran los últimos datos cargados; la solicitud queda en cola.', true);
        break;
      }
      if (e.estado === 'procesando') btn.textContent = 'Procesando…';
    }
  } catch (err) { aviso(`No se pudo pedir la actualización: ${err.message}`, true); }
  finally { btn.disabled = false; btn.textContent = 'Actualizar'; }
});

// ---------- Preguntas (IA) ----------
const SUGERENCIAS = {
  cosecha: '¿Qué cosechas de los últimos 6 meses tienen la peor mora 30+?',
  cartera_activa: '¿Qué sucursales concentran el saldo en mora 30+?',
  primeros_pagos: '¿Qué promotores tienen más primeros pagos en mora este mes?',
  cono: '¿Qué gestores tienen mejor porcentaje de RPC y de promesas?',
};
function sugerencias() {
  const mias = PESTANAS.filter(p => p.roles.includes(rol()));
  $('sugerencias').innerHTML = mias.map(p => `<button type="button">${esc(SUGERENCIAS[p.id])}</button>`).join('');
}
$('sugerencias').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { $('pregunta').value = b.textContent; $('pregunta').focus(); } });

function burbuja(texto, tipo) {
  const d = document.createElement('div');
  d.className = `msg ${tipo}`;
  if (tipo.startsWith('ia')) {
    const img = document.createElement('img'); img.src = 'img/prestamito_explicando.png'; img.alt = '';
    const t = document.createElement('div'); t.textContent = texto;
    d.append(img, t);
  } else d.textContent = texto;
  $('chat').append(d);
  $('chat').scrollTop = $('chat').scrollHeight;
  return d;
}

$('fpregunta').addEventListener('submit', async e => {
  e.preventDefault();
  const q = $('pregunta').value.trim();
  if (!q) return;
  burbuja(q, 'yo');
  $('pregunta').value = '';
  const btn = $('btnPreguntar'); btn.disabled = true; btn.textContent = 'Pensando…';
  try {
    if (LOCAL) throw new Error('La herramienta de preguntas funciona en la app publicada (necesita la función de Supabase).');
    const { data: r, error } = await sb.functions.invoke('cvc-preguntar', { body: { pregunta: q, pestana: S.tab } });
    if (error) {
      let msg = error.message;
      try { msg = (await error.context.json()).error || msg; } catch { /* sin cuerpo JSON */ }
      throw new Error(msg);
    }
    burbuja(r.respuesta, 'ia');
  } catch (err) { burbuja(err.message, 'ia error'); }
  finally { btn.disabled = false; btn.textContent = 'Preguntar'; }
});

// ---------- Administración ----------
async function pintarUsuarios() {
  $('nRol').innerHTML = Object.entries(ROLES).map(([k, t]) => `<option value="${k}">${t}</option>`).join('');
  if (LOCAL) { $('tusuarios').innerHTML = '<tr><td colspan="4">Vista previa local: sin usuarios</td></tr>'; return; }
  try {
    const us = ok(await sb.from('cvc_perfiles').select('*').order('nombre'));
    $('tusuarios').innerHTML = us.map(u => `<tr data-id="${u.id}"><td>${esc(u.nombre)}</td>
      <td><select data-campo="rol">${Object.entries(ROLES).map(([k, t]) => `<option value="${k}"${k === u.rol ? ' selected' : ''}>${t}</option>`).join('')}</select></td>
      <td><input type="checkbox" data-campo="activo"${u.activo ? ' checked' : ''}></td>
      <td><button class="btn mini lin" data-acc="clave">Restablecer contraseña</button></td></tr>`).join('');
  } catch (err) { aviso(err.message, true); }
}

$('fnuevo').addEventListener('submit', async e => {
  e.preventDefault();
  const nombre = $('nNombre').value.trim().replace(/\s+/g, ' ');
  try {
    ok(await sb.rpc('cvc_crear_usuario', { p_usuario: slug(nombre), p_nombre: nombre, p_rol: $('nRol').value, p_password: CLAVE_INICIAL }));
    $('nNombre').value = '';
    alert(`Usuario creado. Ingresa con su nombre completo "${nombre}" y la contraseña ${CLAVE_INICIAL}; la primera vez se le pide cambiarla (si ya usaba Tiempos DAC o Auditores, entra con su contraseña de siempre).`);
    pintarUsuarios();
  } catch (err) { alert(err.message); }
});

$('tusuarios').addEventListener('change', async e => {
  const tr = e.target.closest('tr[data-id]');
  if (!tr) return;
  e.stopPropagation();
  try {
    ok(await sb.rpc('cvc_editar_usuario', { p_id: tr.dataset.id, p_rol: tr.querySelector('[data-campo=rol]').value, p_activo: tr.querySelector('[data-campo=activo]').checked }));
  } catch (err) { alert(err.message); pintarUsuarios(); }
});

$('tusuarios').addEventListener('click', async e => {
  const b = e.target.closest('button[data-acc=clave]');
  if (!b || !confirm(`¿Restablecer la contraseña a ${CLAVE_INICIAL}?`)) return;
  try { ok(await sb.rpc('cvc_restablecer_clave', { p_id: b.closest('tr').dataset.id, p_password: CLAVE_INICIAL })); alert(`Contraseña restablecida a ${CLAVE_INICIAL}.`); }
  catch (err) { alert(err.message); }
});

$('btnClave').addEventListener('click', async () => {
  const actual = prompt('Contraseña actual:');
  if (!actual) return;
  const nueva = prompt('Nueva contraseña (mínimo 8 caracteres). Si usa Tiempos DAC o Auditores, también cambia allá:');
  if (!nueva) return;
  if (nueva.length < 8) return alert('La contraseña debe tener al menos 8 caracteres.');
  if (nueva === CLAVE_INICIAL) return alert('Use una contraseña distinta de la genérica.');
  try {
    ok(await sb.auth.signInWithPassword({ email: S.perfil.usuario + DOMINIO, password: actual }));
    ok(await sb.auth.updateUser({ password: nueva }));
    alert('Contraseña cambiada.');
  } catch { alert('La contraseña actual no es correcta.'); }
});

$('btnSalir').addEventListener('click', async () => { await sb.auth.signOut(); S.perfil = null; S.datos = {}; mostrarLogin(); });

(async () => {
  try {
    if (LOCAL) {
      const r = QS.get('rol') in ROLES ? QS.get('rol') : 'admin';
      S.perfil = { nombre: 'Vista previa local', rol: r, usuario: 'local' };
      return await iniciar();
    }
    S.perfil = await perfilActual();
    if (S.perfil?.activo) await iniciar(); else mostrarLogin();
  } catch (err) { console.error(err.stack || err); mostrarLogin(`No se pudo iniciar: ${err.message}`); }
})();
