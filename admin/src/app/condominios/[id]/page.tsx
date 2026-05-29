'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft, ExternalLink, Upload,
  CheckCircle2, XCircle, Clock, ChevronDown, ChevronRight, Building2
} from 'lucide-react';
import type { CondominioStatus, ImportRecord } from '@/lib/types';
import { ADAPTER_LABELS, ADAPTER_COLORS } from '@/lib/adapter-meta';

function fmt(v?: number): string {
  if (v == null) return '—';
  return v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function fmtDate(ts: string): string {
  const d = new Date(ts);
  return d.toLocaleDateString('pt-BR', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit'
  });
}

export default function CondominioDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [status, setStatus]           = useState<CondominioStatus | null>(null);
  const [history, setHistory]         = useState<ImportRecord[]>([]);
  const [loading, setLoading]         = useState(true);
  const [expandedLog, setExpandedLog] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch('/api/condominios').then(r => r.json()),
      fetch(`/api/historico?condominioId=${id}`).then(r => r.json()),
    ]).then(([cdata, hdata]) => {
      const found = cdata.statuses?.find((s: CondominioStatus) => s.condominio.id === id);
      if (found) setStatus(found);
      if (hdata.records) setHistory(hdata.records);
    }).finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="p-4 sm:p-8">
        <div className="skeleton h-8 w-64 rounded mb-4" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4 mb-6">
          {Array.from({ length: 4 }).map((_, i) => <div key={i} className="skeleton h-20 sm:h-24 rounded-xl" />)}
        </div>
        <div className="skeleton h-48 sm:h-64 rounded-xl" />
      </div>
    );
  }

  if (!status) {
    return (
      <div className="p-4 sm:p-8 text-center py-24">
        <Building2 size={40} className="text-text-disabled mx-auto mb-4" />
        <p className="text-text-secondary">Condomínio não encontrado</p>
        <Link href="/condominios" className="btn-secondary mt-4 inline-flex">Voltar</Link>
      </div>
    );
  }

  const { condominio, lastMonth, lastData } = status;
  const adapterColor = ADAPTER_COLORS[condominio.empresa_gestora] ?? '#6366F1';

  const kpis = [
    { label: 'Saldo atual',   value: fmt(lastData?.tAtual), color: '#22C55E' },
    { label: 'Receita',       value: fmt(lastData?.tCred),  color: '#6366F1' },
    { label: 'Despesa',       value: fmt(lastData?.tDeb),   color: '#EAB308' },
    { label: 'Inadimplência', value: fmt(lastData?.inad),   color: '#EF4444' },
  ];

  return (
    <div className="p-4 sm:p-8 page-enter max-w-5xl">

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 mb-4 sm:mb-6">
        <Link href="/condominios" className="flex items-center gap-1.5 text-text-muted hover:text-text-primary
          text-[12px] transition-colors">
          <ArrowLeft size={13} /> Condomínios
        </Link>
        <span className="text-text-disabled">/</span>
        <span className="text-[12px] text-text-secondary truncate max-w-[180px] sm:max-w-none">
          {condominio.nome}
        </span>
      </div>

      {/* Header — empilhado em mobile */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-5 sm:mb-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl flex-shrink-0"
            style={{ background: `linear-gradient(135deg, ${condominio.cor} 0%, ${condominio.cor}99 100%)` }} />
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-text-primary">{condominio.nome}</h1>
            <div className="flex items-center gap-2 mt-0.5 flex-wrap">
              <span className="text-[11px] font-medium px-1.5 py-0.5 rounded"
                style={{ color: adapterColor, background: `${adapterColor}18` }}>
                {ADAPTER_LABELS[condominio.empresa_gestora] ?? condominio.empresa_gestora}
              </span>
              {lastMonth && (
                <span className="text-[11px] text-text-muted">
                  Último mês: <strong className="text-text-secondary">{lastMonth}</strong>
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Link href="/importar" className="btn-secondary text-[12px]">
            <Upload size={13} /> Importar
          </Link>
          <a href={`/api/dashboard/${condominio.id}`} target="_blank" rel="noopener noreferrer"
            className="btn-primary text-[12px]">
            <ExternalLink size={13} /> Ver Dashboard
          </a>
        </div>
      </div>

      {/* KPIs — 2 colunas mobile, 4 desktop */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4 mb-6 sm:mb-8">
        {kpis.map(({ label, value, color }) => (
          <div key={label} className="card p-3 sm:p-4">
            <p className="text-[10px] sm:text-[11px] text-text-muted uppercase tracking-wide font-semibold mb-1 leading-tight">
              {label}
            </p>
            <p className="text-base sm:text-xl font-bold break-all" style={{ color, fontVariantNumeric: 'tabular-nums' }}>
              {value}
            </p>
          </div>
        ))}
      </div>

      {/* Histórico de importações */}
      <div>
        <h2 className="text-[14px] font-semibold text-text-primary mb-4">Histórico de importações</h2>

        {history.length === 0 ? (
          <div className="card py-10 sm:py-12 text-center">
            <Clock size={32} className="text-text-disabled mx-auto mb-3" />
            <p className="text-text-muted text-[13px]">Nenhuma importação registrada para este condomínio</p>
            <Link href="/importar" className="btn-secondary mt-4 inline-flex text-[12px]">
              Fazer primeira importação
            </Link>
          </div>
        ) : (
          <div className="space-y-2">
            {history.map(r => (
              <div key={r.id}
                className={`border rounded-xl overflow-hidden transition-all duration-150
                  ${expandedLog === r.id ? 'border-border-focus' : 'border-border hover:border-border-focus'}`}>
                <div
                  onClick={() => setExpandedLog(expandedLog === r.id ? null : r.id)}
                  className="flex items-center gap-3 px-3 sm:px-4 py-3 cursor-pointer hover:bg-bg-hover transition-colors">

                  <div className={`p-1.5 rounded-lg flex-shrink-0
                    ${r.status === 'success' ? 'bg-success/10' : 'bg-danger/10'}`}>
                    {r.status === 'success'
                      ? <CheckCircle2 size={14} className="text-success" />
                      : <XCircle size={14} className="text-danger" />
                    }
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[13px] font-semibold text-text-primary font-mono">{r.mes}</span>
                      <span className="text-[11px] text-text-muted truncate max-w-[120px] sm:max-w-xs">{r.arquivo}</span>
                    </div>
                  </div>

                  <span className="text-[11px] text-text-muted flex-shrink-0 hidden sm:inline">
                    {fmtDate(r.timestamp)}
                  </span>
                  <span className="text-[11px] text-text-muted flex-shrink-0 sm:hidden">
                    {new Date(r.timestamp).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })}
                  </span>
                  {expandedLog === r.id
                    ? <ChevronDown size={14} className="text-text-muted" />
                    : <ChevronRight size={14} className="text-text-muted" />
                  }
                </div>

                {expandedLog === r.id && (
                  <div className="border-t border-border bg-bg-base px-3 sm:px-4 py-3">
                    <div className="font-mono text-[11px] space-y-0.5 max-h-40 overflow-y-auto">
                      {r.log.map((line, i) => (
                        <p key={i} className={`leading-relaxed break-all
                          ${line.includes('[OK]')    ? 'text-success'        : ''}
                          ${line.includes('[ERRO]')  ? 'text-danger'         : ''}
                          ${line.includes('[AVISO]') ? 'text-warning'        : ''}
                          ${!line.includes('[')      ? 'text-text-secondary' : ''}
                        `}>{line}</p>
                      ))}
                      {r.error && <p className="text-danger">Erro: {r.error}</p>}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Preview do Dashboard */}
      <div className="mt-6 sm:mt-8">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[14px] font-semibold text-text-primary">Preview do Dashboard</h2>
          <a href={`/api/dashboard/${condominio.id}`} target="_blank" rel="noopener noreferrer"
            className="btn-ghost text-[12px]">
            <ExternalLink size={12} /> Abrir em nova aba
          </a>
        </div>
        <div className="card overflow-hidden" style={{ height: '420px' }}>
          <iframe
            src={`/api/dashboard/${condominio.id}`}
            className="w-full h-full border-0"
            title={`Dashboard ${condominio.nome}`}
          />
        </div>
      </div>
    </div>
  );
}
