const fs = require('fs');
const path = require('path');
const filePath = path.join(__dirname, '..', 'docs', 'Dashboard_Financeiro_VibraButanta.html');
const html = fs.readFileSync(filePath, 'utf8');

const scriptBlocks = [];
const scriptRe = /<script(?![^>]*\bsrc\b)[^>]*>([\s\S]*?)<\/script>/gi;
let m;
while ((m = scriptRe.exec(html)) !== null) scriptBlocks.push(m[1]);

const errors = [];

function makeMockEl(id) {
  const el = {
    id: id, _children: [], innerHTML: '', style: {},
    classList: { _c: new Set(), add(c){this._c.add(c);}, remove(c){this._c.delete(c);},
      toggle(c){if(this._c.has(c)){this._c.delete(c);return false;}this._c.add(c);return true;},
      contains(c){return this._c.has(c);} },
    querySelectorAll: ()=>[], querySelector: ()=>null,
    getAttribute: ()=>null, setAttribute: ()=>{},
    addEventListener: ()=>{},
    appendChild: function(child){ this._children.push(child); },
    insertBefore: function(a,b){ this._children.push(a); },
    get parentNode(){ return {insertBefore:(a,b)=>{}}; },
    textContent: '', value: '', options: [], selectedIndex: 0,
    get childElementCount(){ return this._children.length; }
  };
  return el;
}

const elements = {};
function getOrMake(id) { if (!elements[id]) elements[id] = makeMockEl(id); return elements[id]; }

global.window = {
  onload: null, innerWidth: 1200, _loadListeners: [],
  addEventListener: function(ev, fn){ if(ev==='load') global.window._loadListeners.push(fn); }
};
global.document = {
  getElementById: id => getOrMake(id),
  querySelector: ()=>null, querySelectorAll: ()=>[],
  createElement: tag => makeMockEl('__'+tag+'__'),
  addEventListener: ()=>{}, body: makeMockEl('body')
};
global.console = {
  log: (...a) => process.stdout.write('[LOG] '+a.join(' ')+'\n'),
  error: (...a) => { errors.push(a.join(' ')); process.stdout.write('[ERR] '+a.join(' ')+'\n'); },
  warn: (...a) => process.stdout.write('[WARN] '+a.join(' ')+'\n')
};
global.Chart = function(el,cfg){ return {}; };
global.setTimeout = ()=>{}; global.clearTimeout = ()=>{};

try { eval(scriptBlocks.join('\n')); }
catch(e) { console.error('LOAD ERROR: '+e.message+'\n'+e.stack.split('\n').slice(0,4).join('\n')); process.exit(1); }

console.log('\n=== VALIDATION REPORT ===\n');

if (!global.window.onload) { console.log('ERROR: window.onload is NOT set'); }
else {
  console.log('OK: window.onload is set');
  try { global.window.onload.call(global.window); console.log('OK: window.onload executed without throwing'); }
  catch(e) { console.log('ERROR in window.onload: '+e.message); errors.push(e.message); }
}

global.window._loadListeners.forEach(function(fn,i){
  try{fn();}catch(e){console.log('ERROR load listener '+i+': '+e.message);}
});

console.log('\n--- Errors collected ---');
if(errors.length===0) console.log('None');
else errors.forEach(e=>console.log(' * '+e));

const expectedIds = [
  'sb-info','geral-kpis','geral-alert',
  'bal-pills','balContent',
  'tblDesp','tblPvr','tblInad','tblBanco',
  'orc-content','orc-de','orc-ate'
];

console.log('\n--- Element population status ---');
expectedIds.forEach(id => {
  const el = elements[id];
  const hasInner = el && el.innerHTML && el.innerHTML.length > 0;
  const hasChildren = el && el._children && el._children.length > 0;
  const ok = hasInner || hasChildren;
  const detail = hasInner ? ' ('+el.innerHTML.length+' chars)' : (hasChildren ? ' ('+el._children.length+' children)' : ' (empty)');
  console.log((ok ? 'OK  ' : 'MISS')+' #'+id+detail);
});

console.log('\nDone.');