'use client';

import Link from 'next/link';
import { TrendingUp, AlertCircle, CheckCircle2, Clock, ExternalLink } from 'lucide-react';
import { ADAPTER_COLORS } from '@/lib/adapter-meta';
import type { CondominioStatus } from '@/lib/types';

function fmt(val: number): string {
  if (val >= 1_000_000) return `R$${(val / 1_000_000).toFixed(1)}M`;
  if (val >= 1_000) return `R$${(val / 1_000).toFixed(0)}k`;
  return `R$${val.toFixed(0)}`;
}

const STATUS_CONFIG = {
  current: { color: '#22C55E', bg: 'rgba(34,197,94,0.1)',  border: 'rgba(34,197,94,0.2)',  Icon: CheckCircle2, label: 'Em dia'     },
  pending: { color: '#EAB308', bg: 'rgba(234,179,8,0.1)', border: 'rgba(234,179,8,0.2)',  Icon: Clock,        label: 'Pendente'   },
  error:   { color: '#EF4444', bg: 'rgba(239,68,68,0.1)', border: 'rgba(239,68,68,0.2)',  Icon: AlertCircle,  label: 'Erro'       },
  no_data: { color: '#52525B', bg: 'rgba(82,82,91,0.1)',  border: 'rgba(82,82,91,0.15)', Icon: Clock,        label: 'Sem dados'  },
};

interface Props {
  status: CondominioStatus;
}

export function CondoCard({ status }: Props) {
  const { condominio, lastMonth, lastData } = status;
  const st           = STATUS_CONFIG[status.status];
  const adapterColor = ADAPTER_COLORS[condominio.empresa_gestora] ?? '#6366F1';

  return (
    <div className="group relative card-hover p-4 animate-slide-up overflow-hidden flex flex-col">

      {/* Barra de cor no topo */}
      <div className="absolute top-0 left-0 right-0 h-0.5 rounded-t-xl transition-all duration-300"
        style={{ background: `linear-gradient(90deg, ${condominio.cor} 0%, transparent 100%)` }} />

      {/* Nome + status */}
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-2.5 h-2.5 rounded-full flex-shrink-0 mt-0.5"
            style={{ background: condominio.cor, boxShadow: `0 0 6px ${condominio.cor}60` }} />
          <h3 className="text-[13px] font-semibold text-text-primary leading-tight truncate">
            {condominio.nome}
          </h3>
        </div>
        <span className="flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-md flex-shrink-0"
          style={{ color: st.color, background: st.bg, border: `1px solid ${st.border}` }}>
          <st.Icon size={9} />
          {st.label}
        </span>
      </div>

      {/* Saldo */}
      <div className="mb-3">
        {lastData?.tAtual != null ? (
          <div>
            <p className="text-[10px] text-text-muted mb-0.5">Saldo atual</p>
            <p className="text-lg font-bold text-text-primary leading-none" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {fmt(lastData.tAtual)}
            </p>
          </div>
        ) : (
          <div className="h-7 skeleton rounded w-24" />
        )}
      </div>

      {/* Mês + adapter */}
      <div className="flex items-center justify-between gap-2 mb-3">
        <span className="text-[11px] text-text-secondary font-medium">
          {lastMonth ?? <span className="text-text-muted">—</span>}
        </span>
        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded"
          style={{ color: adapterColor, background: `${adapterColor}18` }}>
          {condominio.empresa_gestora.split('_')[0].toUpperCase()}
        </span>
      </div>

      {/* ── Ações MOBILE (sempre visíveis em telas pequenas) ── */}
      <div className="flex items-center gap-1.5 pt-2 border-t border-border/50 md:hidden">
        <Link href={`/condominios/${condominio.id}`}
          className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg text-[11px]
            text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors duration-150">
          <TrendingUp size={11} />
          Detalhe
        </Link>
        <a href={`/api/dashboard/${condominio.id}`} target="_blank" rel="noopener noreferrer"
          className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg text-[11px]
            text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors duration-150">
          <ExternalLink size={11} />
          Dashboard
        </a>
      </div>

      {/* ── Ações DESKTOP (overlay ao hover) ─────────────────── */}
      <div className="absolute inset-0 bg-bg-hover/40 opacity-0 group-hover:opacity-100 transition-opacity duration-150
                      items-center justify-center gap-2 rounded-xl hidden md:flex">
        <Link href={`/condominios/${condominio.id}`}
          className="btn-secondary text-[12px] px-3 py-1.5">
          <TrendingUp size={12} />
          Detalhe
        </Link>
        <a href={`/api/dashboard/${condominio.id}`} target="_blank" rel="noopener noreferrer"
          className="btn-secondary text-[12px] px-3 py-1.5">
          <ExternalLink size={12} />
          Dashboard
        </a>
      </div>
    </div>
  );
}
