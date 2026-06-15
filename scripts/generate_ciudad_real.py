"""Gera docs/Dashboard_Financeiro_CidadReal.html a partir do template Cinque Terre.
Inclui rec[] (receitas detalhadas por categoria) em cada mês do BAL,
e injeta seção 'Receitas por Categoria' no renderBal() do HTML.
"""
import re, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

with open('docs/Dashboard_Financeiro_CinqueTerre.html', encoding='utf-8') as f:
    html = f.read()

# ── 1. TÍTULO ────────────────────────────────────────────────────────────────
html = html.replace(
    '<title>Dashboard Financeiro – Cinque Terre Residenza</title>',
    '<title>Dashboard Financeiro – Ciudad Real</title>'
)

# ── 2. SIDEBAR ───────────────────────────────────────────────────────────────
html = html.replace('<h2>Cinque Terre</h2>', '<h2>Ciudad Real</h2>')
html = html.replace(
    '185 Residenza &middot; Demonstrativo Financeiro',
    'Ciudad Real &middot; Demonstrativo Financeiro'
)

# ── 3. SUBTÍTULO ─────────────────────────────────────────────────────────────
html = html.replace(
    'Demonstrativo Financeiro &middot; Condom&iacute;nio 185 &ndash; Cinque Terre Residenza',
    'Demonstrativo Financeiro &middot; Condom&iacute;nio Ciudad Real'
)

# ── 4. CONFIG ────────────────────────────────────────────────────────────────
new_config = """var CONFIG = {
  nome: 'Ciudad Real',
  unidades: 0,
  sindica: 'Amanda Renata Morsani Accioli Marti',
  orcamento: {
    exercicio: '2025/2026',
    totalAnual: 1430000,
    meses: {
      abr25: 130000, mai25: 130000, jun25: 130000, jul25: 130000,
      ago25: 130000, set25: 130000, out25: 130000, nov25: 130000,
      dez25: 130000, jan26: 130000, fev26: 130000
    }
  }
};"""
html = re.sub(r'var CONFIG = \{.*?\};', new_config, html, flags=re.DOTALL)

# ── 5. EVO ───────────────────────────────────────────────────────────────────
html = re.sub(
    r"var EVO_L = \[.*?\];",
    "var EVO_L = ['Abr/25','Mai/25','Jun/25','Jul/25','Ago/25','Set/25','Out/25','Nov/25','Dez/25','Jan/26','Fev/26'];",
    html
)
html = re.sub(
    r"var EVO_V = \[.*?\];",
    "var EVO_V = [247889.33,308615.02,291422.86,321544.21,347687.14,332676.85,366054.98,377339.16,366194.65,390472.32,385574.86];",
    html
)

# ── 6. BAL com rec[] detalhado ────────────────────────────────────────────────
# Fontes: imagens PNG 300 DPI; TX CONDOMÍNIO calculado para fechar tCred.
# Rend. Aplicação = rendimentos das contas APLIC + FUNDO RESERVA CDB.
new_bal = """var BAL = {

  // ── Abril / 2025 ───────────────────────────────────────────────
  abr25: {
    tit: 'Abril / 2025', per: '01/04/2025 a 30/04/2025',
    tAnt: 236890.54, tCred: 113710.13, tDeb: 102677.12, tAtual: 247889.33,
    contas: [
      {n:'Aplic. Privilège', a:0, c:0, d:0, s:136582.78},
      {n:'CTA ITAÚ',         a:0, c:0, d:0, s:111301.79}
    ],
    prev: 130000, real: 113428.31, tDesp: 102677.12,
    fac: 0, inad: 0, inadProc: 0,
    banco: {cc:111301.79, cdb:136582.78, priv:0},
    rec: [
      {c:'TX Condomínio',         v:96310.64},
      {c:'Fundo Reserva',         v:4829.38},
      {c:'Reemb. Consumo Água',   v:7009.86},
      {c:'Acordos',               v:3018.69},
      {c:'Churrasqueira',         v:820.00},
      {c:'Rend. Aplic. em C/C',   v:18.22},
      {c:'Infrações/Multa RI',    v:-466.66},
      {c:'Receitas Diversas',     v:461.04},
      {c:'Multa/Juros',           v:281.82},
      {c:'Rend. Aplicação',       v:1427.14}
    ],
    desp: [
      {c:'Manutenção',          v:26956.38},
      {c:'Administrativo',      v:8640.30},
      {c:'Jurídico',            v:1681.60},
      {c:'Consumo',             v:17326.74},
      {c:'Serv. Terceirizados', v:45301.45},
      {c:'Aquisições',          v:2767.60}
    ]
  },

  // ── Maio / 2025 ───────────────────────────────────────────────
  mai25: {
    tit: 'Maio / 2025', per: '01/05/2025 a 31/05/2025',
    tAnt: 247889.55, tCred: 166597.39, tDeb: 105871.92, tAtual: 308615.02,
    contas: [
      {n:'Aplic. Privilège', a:0, c:0, d:0, s:143081.79},
      {n:'CTA ITAÚ',         a:0, c:0, d:0, s:165533.23}
    ],
    prev: 130000, real: 166222.81, tDesp: 105871.92,
    fac: 0, inad: 0, inadProc: 0,
    banco: {cc:165533.23, cdb:143081.79, priv:0},
    rec: [
      {c:'TX Condomínio',         v:140106.50},
      {c:'Fundo Reserva',         v:4940.31},
      {c:'Reemb. Consumo Água',   v:9371.22},
      {c:'Acordos',               v:8214.44},
      {c:'Churrasqueira',         v:984.00},
      {c:'Salão de Festa',        v:1230.00},
      {c:'Rend. Aplic. em C/C',   v:800.22},
      {c:'Infrações/Multa RI',    v:-1866.66},
      {c:'Receitas Diversas',     v:889.73},
      {c:'Multa/Juros',           v:374.58},
      {c:'Rend. Aplicação',       v:1553.05}
    ],
    desp: [
      {c:'Manutenção',          v:14490.91},
      {c:'Administrativo',      v:13886.28},
      {c:'Jurídico',            v:7403.99},
      {c:'Consumo',             v:17244.96},
      {c:'Serv. Terceirizados', v:52845.78}
    ]
  },

  // ── Junho / 2025 ──────────────────────────────────────────────
  jun25: {
    tit: 'Junho / 2025', per: '01/06/2025 a 30/06/2025',
    tAnt: 308615.00, tCred: 124772.63, tDeb: 141964.79, tAtual: 291422.86,
    contas: [
      {n:'Aplic. Privilège', a:0, c:0, d:0, s:149618.17},
      {n:'CTA ITAÚ',         a:0, c:0, d:0, s:141804.69}
    ],
    prev: 130000, real: 124486.63, tDesp: 141964.79,
    fac: 0, inad: 0, inadProc: 0,
    banco: {cc:141804.69, cdb:149618.17, priv:0},
    rec: [
      {c:'TX Condomínio',         v:98529.00},
      {c:'Fundo Reserva',         v:4940.31},
      {c:'Reemb. Consumo Água',   v:9371.22},
      {c:'Acordos',               v:9371.22},
      {c:'Infrações/Multa RI',    v:1602.98},
      {c:'Rend. Aplic. em C/C',   v:-466.66},
      {c:'Multa/Juros',           v:286.00},
      {c:'Rend. Aplicação',       v:1138.56}
    ],
    desp: [
      {c:'Manutenção',          v:33371.71},
      {c:'Administrativo',      v:41123.78},
      {c:'Jurídico',            v:5386.69},
      {c:'Consumo',             v:16596.10},
      {c:'Serv. Terceirizados', v:45486.51}
    ]
  },

  // ── Julho / 2025 ──────────────────────────────────────────────
  jul25: {
    tit: 'Julho / 2025', per: '01/07/2025 a 31/07/2025',
    tAnt: 291422.86, tCred: 146431.68, tDeb: 116310.33, tAtual: 321544.21,
    contas: [
      {n:'Aplic. Ordinária',  a:0, c:0, d:0, s:100000.00},
      {n:'CTA ITAÚ',          a:0, c:0, d:0, s:67659.54},
      {n:'Fundo Reserva CDB', a:0, c:0, d:0, s:153884.67}
    ],
    prev: 130000, real: 146112.66, tDesp: 116310.33,
    fac: 0, inad: 0, inadProc: 0,
    banco: {cc:67659.54, cdb:153884.67, priv:100000},
    rec: [
      {c:'TX Condomínio',         v:110883.52},
      {c:'Fundo Reserva',         v:4940.31},
      {c:'Reemb. Consumo Água',   v:10282.53},
      {c:'Acordos',               v:14647.35},
      {c:'Churrasqueira',         v:928.00},
      {c:'Rend. Aplic. em C/C',   v:56.26},
      {c:'Controle',              v:245.00},
      {c:'Receitas Diversas',     v:2226.07},
      {c:'Multa/Juros',           v:319.03},
      {c:'Rend. Aplicação',       v:1903.61}
    ],
    desp: [
      {c:'Manutenção',          v:38883.59},
      {c:'Administrativo',      v:12574.68},
      {c:'Jurídico',            v:1500.00},
      {c:'Consumo',             v:17854.04},
      {c:'Serv. Terceirizados', v:45286.51},
      {c:'Aquisições',          v:211.31}
    ]
  },

  // ── Agosto / 2025 ────────────────────────────────────────────
  ago25: {
    tit: 'Agosto / 2025', per: '01/08/2025 a 31/08/2025',
    tAnt: 321544.21, tCred: 126552.39, tDeb: 100409.46, tAtual: 347687.14,
    contas: [
      {n:'Aplic. Ordinária',  a:0, c:0, d:0, s:106344.55},
      {n:'CTA ITAÚ',          a:0, c:0, d:0, s:85715.89},
      {n:'Fundo Reserva CDB', a:0, c:0, d:0, s:155626.70}
    ],
    prev: 130000, real: 126116.37, tDesp: 100409.46,
    fac: 0, inad: 0, inadProc: 0,
    banco: {cc:85715.89, cdb:155626.70, priv:106344.55},
    rec: [
      {c:'TX Condomínio',         v:106692.84},
      {c:'Fundo Reserva',         v:5189.68},
      {c:'Reemb. Consumo Água',   v:9579.16},
      {c:'Acordos',               v:3510.00},
      {c:'Churrasqueira',         v:492.00},
      {c:'Controle',              v:584.69},
      {c:'Receitas Diversas',     v:70.00},
      {c:'Multa/Juros',           v:434.02}
    ],
    desp: [
      {c:'Manutenção',          v:29853.00},
      {c:'Administrativo',      v:4228.28},
      {c:'Jurídico',            v:1862.14},
      {c:'Consumo',             v:14936.53},
      {c:'Serv. Terceirizados', v:48969.51},
      {c:'Aquisições',          v:560.00}
    ]
  },

  // ── Setembro / 2025 ─────────────────────────────────────────
  set25: {
    tit: 'Setembro / 2025', per: '01/09/2025 a 30/09/2025',
    tAnt: 347687.14, tCred: 135587.31, tDeb: 150597.60, tAtual: 332676.85,
    contas: [
      {n:'Aplic. Ordinária',  a:0, c:0, d:0, s:107656.42},
      {n:'CTA ITAÚ',          a:0, c:0, d:0, s:57309.35},
      {n:'Fundo Reserva CDB', a:0, c:0, d:0, s:167811.08}
    ],
    prev: 130000, real: 135017.86, tDesp: 150597.60,
    fac: 0, inad: 0, inadProc: 0,
    banco: {cc:57309.35, cdb:167811.08, priv:107656.42},
    rec: [
      {c:'TX Condomínio',         v:106397.86},
      {c:'Fundo Reserva',         v:5317.66},
      {c:'Reemb. Consumo Água',   v:12485.28},
      {c:'Acordos',               v:6556.98},
      {c:'Churrasqueira',         v:656.00},
      {c:'Rend. Aplic. em C/C',   v:20.16},
      {c:'Infrações/Multa RI',    v:569.66},
      {c:'Multa/Juros',           v:392.46},
      {c:'Rend. Aplicação',       v:3191.25}
    ],
    desp: [
      {c:'Manutenção',          v:38450.23},
      {c:'Administrativo',      v:11306.92},
      {c:'Jurídico',            v:1518.00},
      {c:'Consumo',             v:16561.81},
      {c:'Serv. Terceirizados', v:82760.64}
    ]
  },

  // ── Outubro / 2025 ───────────────────────────────────────────
  out25: {
    tit: 'Outubro / 2025', per: '01/10/2025 a 31/10/2025',
    tAnt: 332876.85, tCred: 150052.90, tDeb: 116874.80, tAtual: 366054.98,
    contas: [
      {n:'Aplic. Ordinária',  a:0, c:0, d:0, s:109002.90},
      {n:'CTA ITAÚ',          a:0, c:0, d:0, s:81977.70},
      {n:'Fundo Reserva CDB', a:0, c:0, d:0, s:175074.33}
    ],
    prev: 130000, real: 149602.23, tDesp: 116874.80,
    fac: 0, inad: 0, inadProc: 0,
    banco: {cc:81977.70, cdb:175074.33, priv:109002.90},
    rec: [
      {c:'TX Condomínio',         v:107683.45},
      {c:'Fundo Reserva',         v:5394.27},
      {c:'Reemb. Consumo Água',   v:10364.28},
      {c:'Acordos',               v:7313.21},
      {c:'Churrasqueira',         v:862.52},
      {c:'Rend. Aplic. em C/C',   v:38.72},
      {c:'Controle',              v:35.00},
      {c:'Ressarcimento',         v:14400.00},
      {c:'Receitas Diversas',     v:3.00},
      {c:'Multa/Juros',           v:450.70},
      {c:'Rend. Aplicação',       v:3506.75}
    ],
    desp: [
      {c:'Manutenção',          v:46231.95},
      {c:'Administrativo',      v:14636.86},
      {c:'Jurídico',            v:2015.84},
      {c:'Consumo',             v:18401.67},
      {c:'Serv. Terceirizados', v:33843.68},
      {c:'Aquisições',          v:1744.80}
    ]
  },

  // ── Novembro / 2025 ─────────────────────────────────────────
  nov25: {
    tit: 'Novembro / 2025', per: '01/11/2025 a 30/11/2025',
    tAnt: 366054.98, tCred: 125885.33, tDeb: 114601.15, tAtual: 377339.16,
    contas: [
      {n:'Aplic. Ordinária',  a:0, c:0, d:0, s:109306.72},
      {n:'CTA ITAÚ',          a:0, c:0, d:0, s:85942.86},
      {n:'Fundo Reserva CDB', a:0, c:0, d:0, s:181999.58}
    ],
    prev: 130000, real: 125584.68, tDesp: 114601.15,
    fac: 0, inad: 0, inadProc: 0,
    banco: {cc:85942.86, cdb:181999.58, priv:109306.72},
    rec: [
      {c:'TX Condomínio',         v:101642.74},
      {c:'Fundo Reserva',         v:1120.78},
      {c:'Reemb. Consumo Água',   v:10163.46},
      {c:'Acordos',               v:7454.58},
      {c:'Churrasqueira',         v:138.00},
      {c:'Rend. Aplic. em C/C',   v:13.98},
      {c:'Infrações/Multa RI',    v:719.66},
      {c:'Controle',              v:345.00},
      {c:'Receitas Diversas',     v:1074.67},
      {c:'Multa/Juros',           v:300.65},
      {c:'Rend. Aplicação',       v:2911.81}
    ],
    desp: [
      {c:'Manutenção',          v:24468.59},
      {c:'Administrativo',      v:20225.06},
      {c:'Consumo',             v:19173.72},
      {c:'Serv. Terceirizados', v:49357.85},
      {c:'Aquisições',          v:1375.13}
    ]
  },

  // ── Dezembro / 2025 ─────────────────────────────────────────
  dez25: {
    tit: 'Dezembro / 2025', per: '01/12/2025 a 31/12/2025',
    tAnt: 377339.16, tCred: 129216.22, tDeb: 140360.73, tAtual: 366194.65,
    contas: [
      {n:'Aplic. Ordinária',  a:0, c:0, d:0, s:110736.81},
      {n:'CTA ITAÚ',          a:0, c:0, d:0, s:71299.01},
      {n:'Fundo Reserva CDB', a:0, c:0, d:0, s:184157.93}
    ],
    prev: 130000, real: 128777.63, tDesp: 140360.73,
    fac: 0, inad: 0, inadProc: 0,
    banco: {cc:71299.01, cdb:184157.93, priv:110736.81},
    rec: [
      {c:'TX Condomínio',         v:103247.36},
      {c:'Fundo Reserva',         v:5162.50},
      {c:'Reemb. Consumo Água',   v:9865.40},
      {c:'Acordos',               v:6164.60},
      {c:'Churrasqueira',         v:820.00},
      {c:'Rend. Aplic. em C/C',   v:12.64},
      {c:'Multa/Juros',           v:444.78},
      {c:'Rend. Aplicação',       v:3498.94}
    ],
    desp: [
      {c:'Manutenção',          v:38639.78},
      {c:'Administrativo',      v:15046.38},
      {c:'Jurídico',            v:11381.67},
      {c:'Consumo',             v:18533.30},
      {c:'Serv. Terceirizados', v:52604.63},
      {c:'Aquisições',          v:4154.99}
    ]
  },

  // ── Janeiro / 2026 ──────────────────────────────────────────
  jan26: {
    tit: 'Janeiro / 2026', per: '01/01/2026 a 31/01/2026',
    tAnt: 366194.65, tCred: 120299.55, tDeb: 96021.88, tAtual: 390472.32,
    contas: [
      {n:'Aplic. Ordinária',  a:0, c:0, d:0, s:112009.18},
      {n:'CTA ITAÚ',          a:0, c:0, d:0, s:92301.11},
      {n:'Fundo Reserva CDB', a:0, c:0, d:0, s:186242.03}
    ],
    prev: 130000, real: 119919.97, tDesp: 96021.88,
    fac: 0, inad: 0, inadProc: 0,
    banco: {cc:92301.11, cdb:186242.03, priv:112009.18},
    rec: [
      {c:'TX Condomínio',         v:96243.19},
      {c:'Fundo Reserva',         v:4722.50},
      {c:'Reemb. Consumo Água',   v:9879.24},
      {c:'Acordos',               v:5135.25},
      {c:'Churrasqueira',         v:656.00},
      {c:'Salão de Festa',        v:100.00},
      {c:'Rend. Aplic. em C/C',   v:8.22},
      {c:'Multa/Juros',           v:179.58},
      {c:'Rend. Aplicação',       v:3375.57}
    ],
    desp: [
      {c:'Manutenção',          v:16502.18},
      {c:'Administrativo',      v:11731.30},
      {c:'Jurídico',            v:1603.26},
      {c:'Consumo',             v:18057.70},
      {c:'Serv. Terceirizados', v:47084.84},
      {c:'Aquisições',          v:1042.60}
    ]
  },

  // ── Fevereiro / 2026 ───────────────────────────────────────
  fev26: {
    tit: 'Fevereiro / 2026', per: '01/02/2026 a 28/02/2026',
    tAnt: 390472.32, tCred: 120821.76, tDeb: 125719.22, tAtual: 385574.86,
    contas: [
      {n:'Aplic. Ordinária',  a:0, c:0, d:0, s:113132.06},
      {n:'CTA ITAÚ',          a:0, c:0, d:0, s:79577.80},
      {n:'Fundo Reserva CDB', a:0, c:0, d:0, s:192864.20}
    ],
    prev: 130000, real: 120497.25, tDesp: 125719.22,
    fac: 0, inad: 0, inadProc: 0,
    banco: {cc:79577.80, cdb:192864.20, priv:113132.06},
    rec: [
      {c:'TX Condomínio',         v:101604.89},
      {c:'Fundo Reserva',         v:4620.07},
      {c:'Reemb. Consumo Água',   v:10021.78},
      {c:'Acordos',               v:620.07},
      {c:'Churrasqueira',         v:495.00},
      {c:'Rend. Aplic. em C/C',   v:16.49},
      {c:'Controle',              v:210.00},
      {c:'Multa/Juros',           v:324.51},
      {c:'Rend. Aplicação',       v:2908.95}
    ],
    desp: [
      {c:'Manutenção',          v:36982.47},
      {c:'Administrativo',      v:12696.32},
      {c:'Consumo',             v:19085.62},
      {c:'Serv. Terceirizados', v:56954.81}
    ]
  }

};"""

bal_start = html.find('var BAL = {')
meses_start = html.find('var MESES = Object.keys(BAL);')
html = html[:bal_start] + new_bal + '\n\n' + html[meses_start:]

# ── 7. prc() helper ──────────────────────────────────────────────────────────
if 'function prc(' not in html:
    prc_fn = "\nfunction prc(k){var o=CONFIG.orcamento;return(o&&o.meses&&o.meses[k]!==undefined)?o.meses[k]:BAL[k].prev;}\n"
    idx = html.find('var MESES = Object.keys(BAL);') + len('var MESES = Object.keys(BAL);')
    html = html[:idx] + prc_fn + html[idx:]

html = re.sub(r'BAL\[k\]\.prev', 'prc(k)', html)

# ── 8. Injeta seção "Receitas por Categoria" no renderBal() ──────────────────
# Insere antes da seção de despesas (h += '<div class="cc"><h3>&#128184; Despesas)
REC_SECTION = r"""
  if (m.rec && m.rec.length) {
    h += '<div class="cc"><h3>&#128178; Receitas por Categoria &ndash; ' + m.tit + '</h3><div class="tw"><table>';
    h += '<tr><th>Categoria</th><th>Valor</th><th>%</th><th>Participação</th></tr>';
    m.rec.forEach(function(r) {
      var pct = m.tCred > 0 ? (r.v / m.tCred * 100).toFixed(1) : '0.0';
      var sc = r.v < 0 ? ' style="color:var(--r)"' : '';
      h += '<tr><td>' + r.c + '</td>';
      h += '<td class="nr"' + sc + '>' + R(r.v) + '</td>';
      h += '<td class="nr">' + pct + '%</td>';
      h += '<td style="min-width:120px"><div class="pb"><div class="pbf" style="width:' + (r.v > 0 ? pct : '0') + '%"></div></div></td></tr>';
    });
    h += '<tr class="tot"><td>TOTAL RECEITAS</td><td class="nr">' + R(m.tCred) + '</td><td colspan="2"></td></tr>';
    h += '</table></div></div>';
  }
"""

# Localiza o ponto de inserção: antes da seção de despesas dentro de renderBal
DESP_MARKER = "h += '<div class=\"cc\"><h3>&#128184; Despesas por Categoria"
idx_desp = html.find(DESP_MARKER)
if idx_desp >= 0:
    html = html[:idx_desp] + REC_SECTION + '  ' + html[idx_desp:]
else:
    print("AVISO: marcador de despesas não encontrado — seção de receitas não injetada")

# ── 9. Limpa referências residuais ───────────────────────────────────────────
html = html.replace("'Cinque Terre Residenza'", "'Ciudad Real'")
html = html.replace('"Cinque Terre Residenza"', '"Ciudad Real"')
html = html.replace("'Cinque Terre'", "'Ciudad Real'")
html = html.replace('"Cinque Terre"', '"Ciudad Real"')
html = html.replace('Amanda Accioli', 'Amanda Renata Morsani Accioli Marti')
html = html.replace('Cinque Terre', 'Ciudad Real')

# ── 10. Remove card F. Fachada da Visão Geral ────────────────────────────────
html = re.sub(
    r"kpi\('Despesas \(excl\.[^']*\)',\s*R\(totalDesp\),\s*'r',\s*'Incl\. Fundo Fachada'\)\s*\+\s*kpi\('F\. Fachada[^;]+;",
    "kpi('Despesas (excl. ' + primeiro.tit.split(' ')[0] + '/' + primeiro.tit.split(' ')[2] + ')',\n        R(totalDesp), 'r', 'Despesas totais do per&iacute;odo');",
    html
)

# ── 11. Corrige labels "Privilege (Fachada)" → "Aplic. Ordinária" ─────────────
html = html.replace(
    "<th>Privilege (Fachada)</th>",
    "<th>Aplic. Ordin&aacute;ria</th>"
)
html = html.replace(
    "label: 'Privilege (Fachada)',",
    "label: 'Aplic. Ordinária',"
)

# ── 12. Remove referência a Fundo Fachada no alerta de déficit ────────────────
html = html.replace(
    ', principalmente pelo desembolso do Fundo Fachada para reforma.',
    '.'
)

with open('docs/Dashboard_Financeiro_CidadReal.html', 'w', encoding='utf-8') as f:
    f.write(html)

print(f'Gerado! Tamanho: {len(html):,} bytes')

# Verificações
assert 'Ciudad Real' in html
assert 'rec:' in html
assert 'Receitas por Categoria' in html.replace('\\u', 'u')
bal_cnt = html.count("tit: '")
print(f'Meses no BAL: {bal_cnt}')

# Valida que sum(rec[]) ≈ tCred para cada mês
import ast, json
for mes, tcred in [
    ('abr25',113710.13),('mai25',166597.39),('jun25',124772.63),
    ('jul25',146431.68),('ago25',126552.39),('set25',135587.31),
    ('out25',150052.90),('nov25',125885.33),('dez25',129216.22),
    ('jan26',120299.55),('fev26',120821.76)]:
    # extrai rec[] via regex
    pat = mes + r":\s*\{[^}]*rec:\s*\[([^\]]+)\]"
    m = re.search(pat, html, re.DOTALL)
    if m:
        items_str = m.group(1)
        vals = [float(x) for x in re.findall(r'v:([-\d.]+)', items_str)]
        total = round(sum(vals), 2)
        ok = abs(total - tcred) < 0.02
        print(f'  {mes}: sum(rec)={total:.2f} vs tCred={tcred} → {"OK" if ok else "ERRO diff="+str(round(total-tcred,2))}')
