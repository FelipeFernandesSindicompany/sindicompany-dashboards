'use client';

import { useState, useEffect } from 'react';
import { History, CheckCircle2, XCircle, AlertTriangle, ChevronDown, ChevronRight, Search } from 'lucide-react';
import type { ImportRecord } from '@/lib/types';

function relTime(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'agora';
  if (m < 60) return `${m}min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d`;
}

function fmtDate(ts: string): string {
  const d = new Date(ts);
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' }) +
    ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

const STATUS_CONFIG = {
  success: { Icon: CheckCircle2,  color: '#22C55E', bg: 'rgba(34,197,94,0.1)',  border: 'rgba(34,197,94,0.2)',  label: 'Sucesso' },
  error:   { Icon: XCircle,       color: '#EF4444', bg: 'rgba(239,68,68,0.1)',  border: 'rgba(239,68,68,0.2)',  label: 'Erro'    },
  warning: { Icon: AlertTriangle, color: '#EAB308', bg: 'rgba(234,179,8,0.1)',  border: 'rgba(234,179,8,0.2)',  label: 'Aviso'   },
};

function LogRow({ record }: { record: ImportRecord }) {
  const [expanded, setExpanded] = useState(false);
  const st = STATUS_CONFIG[record.status];

  return (
    <div className={`border rounded-xl overflow-hidden transition-all duration-200
      ${expanded ? 'border-border-focus' : 'border-border hover:border-border-focus'}`}>

      <div onClick={() => setExpanded(v => !v)}
        className="flex items-center gap-3 px-3 sm:px-4 py-3 cursor-pointer hover:bg-bg-hover transition-colors">

        {/* Ícone de status */}
        <div className="p-1.5 rounded-lg flex-shrink-0" style={{ background: st.bg, border: `1px solid ${st.border}` }}>
          <st.Icon size={14} style={{ color: st.color }} />
        </div>

        {/* Info principal */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap">
            <span className="text-[13px] font-semibold text-text-primary truncate max-w-[160px] sm:max-w-none">
              {record.condominioNome}
            </span>
            <span className="text-[11px] text-text-muted font-mono">{record.mes}</span>
            <span className="hidden sm:inline text-[10px] text-text-muted px-1.5 py-0.5 bg-bg-elevated rounded font-mono truncate max-w-[200px]">
              {record.arquivo}
            </span>
          </div>
        </div>

        {/* Direita: tempo relativo (mobile) ou data completa (desktop) + badge + chevron */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {/* Tempo relativo no mobile */}
          <span className="sm:hidden text-[11px] text-text-muted">{relTime(record.timestamp)}</span>
          {/* Data completa no desktop */}
          <span className="hidden sm:inline text-[11px] text-text-muted">{fmtDate(record.timestamp)}</span>

          <span className="text-[10px] font-medium px-2 py-0.5 rounded-full hidden sm:inline"
            style={{ color: st.color, background: st.bg, border: `1px solid ${st.border}` }}>
            {st.label}
          </span>
          {expanded
            ? <ChevronDown size={14} className="text-text-muted" />
            : <ChevronRight size={14} className="text-text-muted" />
          }
        </div>
      </div>

      {/* Log expandido */}
      {expanded && (
        <div className="border-t border-border bg-bg-base px-3 sm:px-4 py-3">
          <p className="text-[10px] text-text-muted uppercase tracking-wider font-semibold mb-2">Log de execução</p>
          <div className="font-mono text-[11px] space-y-0.5 max-h-48 overflow-y-auto">
            {record.log.length > 0
              ? record.log.map((line, i) => (
                  <p key={i} className={`leading-relaxed break-all
                    ${line.includes('[OK]')    ? 'text-success'        : ''}
                    ${line.includes('[ERRO]')  ? 'text-danger'         : ''}
                    ${line.includes('[AVISO]') ? 'text-warning'        : ''}
                    ${!line.includes('[')      ? 'text-text-secondary' : ''}
                  `}>
                    {line}
                  </p>
                ))
              : <p className="text-text-muted">Sem log disponível</p>
            }
            {record.error && (
              <p className="text-danger mt-1">Erro: {record.error}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function HistoricoPage() {
  const [records, setRecords]         = useState<ImportRecord[]>([]);
  const [loading, setLoading]         = useState(true);
  const [search, setSearch]           = useState('');
  const [filterStatus, setFilterStatus] = useState('');

  useEffect(() => {
    fetch('/api/historico?limit=200')
      .then(r => r.json())
      .then(d => { if (d.records) setRecords(d.records); })
      .finally(() => setLoading(false));
  }, []);

  const filtered = records.filter(r => {
    const matchSearch = !search ||
      r.condominioNome.toLowerCase().includes(search.toLowerCase()) ||
      r.mes.includes(search);
    const matchStatus = !filterStatus || r.status === filterStatus;
    return matchSearch && matchStatus;
  });

  const successCount = records.filter(r => r.status === 'success').length;
  const errorCount   = records.filter(r => r.status === 'error').length;

  return (
    <div className="p-4 sm:p-8 page-enter max-w-4xl">

      {/* Header */}
      <div className="flex items-center justify-between mb-5 sm:mb-6">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-text-primary">Histórico</h1>
          <p className="text-text-muted text-[12px] sm:text-[13px] mt-1">
            {records.length} importações registradas
            {successCount > 0 && ` · ${successCount} com sucesso`}
            {errorCount   > 0 && ` · ${errorCount} com erro`}
          </p>
        </div>
      </div>

      {/* Stats — 1 coluna mobile, 3 desktop */}
      {records.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4 mb-5 sm:mb-6">
          {[
            { label: 'Total importações', value: records.length, color: '#6366F1' },
            { label: 'Com sucesso',       value: successCount,   color: '#22C55E' },
            { label: 'Com erro',          value: errorCount,     color: '#EF4444' },
          ].map(({ label, value, color }) => (
            <div key={label} className="card px-4 py-3 flex items-center gap-3">
              <div className="w-2 h-8 rounded-full flex-shrink-0" style={{ background: color }} />
              <div>
                <p className="text-xl font-bold text-text-primary">{value}</p>
                <p className="text-[11px] text-text-muted">{label}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-2 sm:gap-3 mb-4 sm:mb-5">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input type="text" placeholder="Buscar..." value={search}
            onChange={e => setSearch(e.target.value)} className="input pl-9" />
        </div>
        <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
          className="input w-auto text-[12px]">
          <option value="">Todos os status</option>
          <option value="success">Sucesso</option>
          <option value="error">Erro</option>
          <option value="warning">Aviso</option>
        </select>
        {(search || filterStatus) && (
          <button onClick={() => { setSearch(''); setFilterStatus(''); }}
            className="btn-ghost text-[12px]">Limpar</button>
        )}
        <span className="ml-auto text-[12px] text-text-muted whitespace-nowrap">
          {filtered.length} resultado{filtered.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Registros */}
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="skeleton h-14 rounded-xl" />
          ))}
        </div>
      ) : filtered.length > 0 ? (
        <div className="space-y-2">
          {filtered.map(r => <LogRow key={r.id} record={r} />)}
        </div>
      ) : (
        <div className="py-16 sm:py-20 text-center">
          <History size={36} className="text-text-disabled mx-auto mb-4" />
          <p className="text-text-secondary font-medium">
            {records.length === 0 ? 'Nenhuma importação registrada ainda' : 'Nenhum resultado encontrado'}
          </p>
          <p className="text-text-muted text-[12px] mt-1">
            {records.length === 0 && 'Faça a primeira importação na página de Importar'}
          </p>
        </div>
      )}
    </div>
  );
}
