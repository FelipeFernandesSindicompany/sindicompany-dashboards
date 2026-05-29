'use client';

import { useState, useEffect } from 'react';
import { Search, Building2, ExternalLink } from 'lucide-react';
import Link from 'next/link';
import { ADAPTER_LABELS, ADAPTER_COLORS } from '@/lib/adapter-meta';
import type { CondominioStatus } from '@/lib/types';

function fmt(val?: number): string {
  if (!val) return '—';
  if (val >= 1_000_000) return `R$${(val / 1_000_000).toFixed(2)}M`;
  if (val >= 1_000) return `R$${(val / 1_000).toFixed(1)}k`;
  return `R$${val.toFixed(0)}`;
}

const STATUS_LABELS = {
  current: { label: 'Em dia',    cls: 'text-success bg-success/10 border-success/20' },
  pending: { label: 'Pendente',  cls: 'text-warning bg-warning/10 border-warning/20' },
  error:   { label: 'Erro',      cls: 'text-danger bg-danger/10 border-danger/20'    },
  no_data: { label: 'Sem dados', cls: 'text-text-muted bg-bg-elevated border-border'  },
};

export default function CondominiosPage() {
  const [statuses, setStatuses]         = useState<CondominioStatus[]>([]);
  const [loading, setLoading]           = useState(true);
  const [search, setSearch]             = useState('');
  const [filterAdapter, setFilterAdapter] = useState('');
  const [filterStatus, setFilterStatus]   = useState('');

  useEffect(() => {
    fetch('/api/condominios')
      .then(r => r.json())
      .then(d => { if (d.statuses) setStatuses(d.statuses); })
      .finally(() => setLoading(false));
  }, []);

  const filtered = statuses.filter(s => {
    const matchSearch  = !search        || s.condominio.nome.toLowerCase().includes(search.toLowerCase());
    const matchAdapter = !filterAdapter || s.condominio.empresa_gestora === filterAdapter;
    const matchStatus  = !filterStatus  || s.status === filterStatus;
    return matchSearch && matchAdapter && matchStatus;
  });

  const adapters = Array.from(new Set(statuses.map(s => s.condominio.empresa_gestora)));

  return (
    <div className="p-4 sm:p-8 page-enter">

      {/* Header */}
      <div className="flex items-center justify-between mb-5 sm:mb-6">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-text-primary">Condomínios</h1>
          <p className="text-text-muted text-[12px] sm:text-[13px] mt-1">
            {statuses.length} condomínios ativos
          </p>
        </div>
      </div>

      {/* Filtros — empilhados em mobile */}
      <div className="flex flex-wrap items-center gap-2 sm:gap-3 mb-5 sm:mb-6">
        <div className="relative w-full sm:flex-1 sm:max-w-xs">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            type="text"
            placeholder="Buscar condomínio..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="input pl-9"
          />
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <select value={filterAdapter} onChange={e => setFilterAdapter(e.target.value)}
            className="input w-auto text-[12px]">
            <option value="">Todos os adapters</option>
            {adapters.map(a => (
              <option key={a} value={a}>{ADAPTER_LABELS[a] ?? a}</option>
            ))}
          </select>

          <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
            className="input w-auto text-[12px]">
            <option value="">Todos os status</option>
            <option value="current">Em dia</option>
            <option value="pending">Pendente</option>
            <option value="error">Erro</option>
            <option value="no_data">Sem dados</option>
          </select>

          {(search || filterAdapter || filterStatus) && (
            <button onClick={() => { setSearch(''); setFilterAdapter(''); setFilterStatus(''); }}
              className="btn-ghost text-[12px]">
              Limpar
            </button>
          )}
        </div>

        <span className="w-full sm:w-auto sm:ml-auto text-[12px] text-text-muted">
          {filtered.length} resultado{filtered.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Tabela com scroll horizontal em mobile */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[600px]">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-3 text-[11px] font-semibold text-text-muted uppercase tracking-wider">Condomínio</th>
                <th className="text-left px-4 py-3 text-[11px] font-semibold text-text-muted uppercase tracking-wider">Adapter</th>
                <th className="text-left px-4 py-3 text-[11px] font-semibold text-text-muted uppercase tracking-wider">Último mês</th>
                <th className="text-right px-4 py-3 text-[11px] font-semibold text-text-muted uppercase tracking-wider">Saldo</th>
                <th className="text-right px-4 py-3 text-[11px] font-semibold text-text-muted uppercase tracking-wider hidden sm:table-cell">Inadimplência</th>
                <th className="text-center px-4 py-3 text-[11px] font-semibold text-text-muted uppercase tracking-wider">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {loading
                ? Array.from({ length: 8 }).map((_, i) => (
                    <tr key={i} className="border-b border-border/50">
                      <td colSpan={7} className="px-4 py-3">
                        <div className="skeleton h-4 rounded w-full" />
                      </td>
                    </tr>
                  ))
                : filtered.map(s => {
                    const { condominio, lastMonth, lastData, status } = s;
                    const st = STATUS_LABELS[status];
                    const ac = ADAPTER_COLORS[condominio.empresa_gestora] ?? '#6366F1';

                    return (
                      <tr key={condominio.id}
                        className="border-b border-border/50 hover:bg-bg-hover transition-colors duration-100 group">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2.5">
                            <div className="w-2 h-2 rounded-full flex-shrink-0"
                              style={{ background: condominio.cor }} />
                            <span className="text-[13px] font-medium text-text-primary">{condominio.nome}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-[11px] font-medium px-1.5 py-0.5 rounded"
                            style={{ color: ac, background: `${ac}18` }}>
                            {condominio.empresa_gestora.split('_')[0].toUpperCase()}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-[12px] text-text-secondary font-medium">
                            {lastMonth ?? <span className="text-text-muted">—</span>}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <span className="text-[12px] font-semibold text-text-primary" style={{ fontVariantNumeric: 'tabular-nums' }}>
                            {fmt(lastData?.tAtual)}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right hidden sm:table-cell">
                          <span className="text-[12px] text-danger" style={{ fontVariantNumeric: 'tabular-nums' }}>
                            {lastData?.inad ? fmt(lastData.inad) : '—'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-center">
                          <span className={`badge border text-[10px] ${st.cls}`}>{st.label}</span>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                            <Link href={`/condominios/${condominio.id}`}
                              className="p-1.5 rounded hover:bg-bg-elevated text-text-muted hover:text-text-primary transition-colors">
                              <Building2 size={13} />
                            </Link>
                            <a href={`/api/dashboard/${condominio.id}`} target="_blank" rel="noopener noreferrer"
                              className="p-1.5 rounded hover:bg-bg-elevated text-text-muted hover:text-text-primary transition-colors">
                              <ExternalLink size={13} />
                            </a>
                          </div>
                        </td>
                      </tr>
                    );
                  })
              }
            </tbody>
          </table>
        </div>

        {!loading && filtered.length === 0 && (
          <div className="py-16 text-center">
            <Building2 size={32} className="text-text-disabled mx-auto mb-3" />
            <p className="text-text-muted text-[13px]">Nenhum condomínio encontrado</p>
          </div>
        )}
      </div>
    </div>
  );
}
