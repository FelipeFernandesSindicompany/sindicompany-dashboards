import { Building2, CheckCircle2, Clock, AlertCircle, TrendingUp } from 'lucide-react';
import Link from 'next/link';
import { getCondominios } from '@/lib/condominios';
import { extractBAL } from '@/lib/htmlExtractor';
import { getLastImportByCondominio } from '@/lib/history';
import { CondoCard } from '@/components/condominios/CondoCard';
import type { CondominioStatus } from '@/lib/types';

export const dynamic = 'force-dynamic';

/** Calcula o mês esperado (2 meses atrás) como chave "mmmAA", ex: "abr26" */
function getExpectedMonth(): string {
  const now = new Date();
  const abbrs = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
  const d = new Date(now.getFullYear(), now.getMonth() - 2, 1);
  return `${abbrs[d.getMonth()]}${String(d.getFullYear()).slice(2)}`;
}

/** Label legível do mês esperado, ex: "Abr/26" */
function getExpectedMonthLabel(): string {
  const now = new Date();
  const abbrs = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
  const labels = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
  const d = new Date(now.getFullYear(), now.getMonth() - 2, 1);
  return `${labels[d.getMonth()]}/${String(d.getFullYear()).slice(2)}`;
}

function buildStatuses(): CondominioStatus[] {
  const condominios = getCondominios();
  const lastImports = getLastImportByCondominio();

  const now = new Date();
  const abbrs = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];

  // Regra de negócio: prestações chegam com 2 meses de defasagem.
  // Em junho/2026 o mês esperado é abril/2026 → dashboards em abr26 = "Em dia"
  const expectedDate = new Date(now.getFullYear(), now.getMonth() - 2, 1);
  const expectedMonth = `${abbrs[expectedDate.getMonth()]}${String(expectedDate.getFullYear()).slice(2)}`;

  return condominios
    .map(condo => {
      const bal = extractBAL(condo.html_file);
      const lastImport = lastImports[condo.id] ?? null;

      let status: CondominioStatus['status'] = 'no_data';
      if (bal) {
        status = bal.lastKey === expectedMonth ? 'current' : 'pending';
      }
      if (lastImport?.status === 'error') status = 'error';

      return {
        condominio: condo,
        lastKey: bal?.lastKey ?? null,
        lastMonth: bal?.lastMonth ?? null,
        lastData: bal ? (bal.data as any) : null,
        lastImport,
        status,
      };
    })
    .sort((a, b) =>
      a.condominio.nome.localeCompare(b.condominio.nome, 'pt-BR', { sensitivity: 'base' })
    );
}

export default function HomePage() {
  const statuses = buildStatuses();
  const expectedLabel = getExpectedMonthLabel();

  const total   = statuses.length;
  const current = statuses.filter(s => s.status === 'current').length;
  const pending = statuses.filter(s => s.status === 'pending').length;
  const errors  = statuses.filter(s => s.status === 'error').length;
  const noData  = statuses.filter(s => s.status === 'no_data').length;

  const lastImportTime = (() => {
    const sorted = statuses
      .filter(s => s.lastImport)
      .sort((a, b) => b.lastImport!.timestamp.localeCompare(a.lastImport!.timestamp));
    if (!sorted.length) return null;
    const d = new Date(sorted[0].lastImport!.timestamp);
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' }) + ', ' +
           d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  })();

  const kpis = [
    { label: 'Total',      value: total,          icon: Building2,    color: '#6366F1', suffix: '' },
    { label: 'Atualizados',value: current,         icon: CheckCircle2, color: '#22C55E', suffix: `/${total}` },
    { label: 'Pendentes',  value: pending + noData, icon: Clock,       color: '#EAB308', suffix: '' },
    { label: 'Com erro',   value: errors,           icon: AlertCircle, color: '#EF4444', suffix: '' },
  ];

  return (
    <div className="p-4 sm:p-8 page-enter">

      {/* ── Header ─────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6 sm:mb-8">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-text-primary">Visão Geral</h1>
          <p className="text-text-muted text-[12px] sm:text-[13px] mt-1">
            {total} condomínios · {current} atualizados com {expectedLabel}
            {lastImportTime && ` · Última: ${lastImportTime}`}
          </p>
        </div>
        <Link href="/importar" className="btn-primary self-start sm:self-auto">
          <TrendingUp size={15} />
          Importar mês
        </Link>
      </div>

      {/* ── KPI cards — 2 colunas mobile, 4 desktop ────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4 mb-6 sm:mb-8">
        {kpis.map(({ label, value, icon: Icon, color, suffix }) => (
          <div key={label} className="card p-3 sm:p-4 relative overflow-hidden">
            <div className="absolute top-0 right-0 w-16 h-16 sm:w-20 sm:h-20 rounded-full opacity-5 -translate-y-4 translate-x-4 sm:-translate-y-6 sm:translate-x-6"
              style={{ background: color }} />
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[10px] sm:text-[11px] text-text-muted font-medium uppercase tracking-wide mb-1 leading-tight">
                  {label}
                </p>
                <p className="text-2xl sm:text-3xl font-bold leading-none" style={{ color }}>
                  {value}
                  <span className="text-sm sm:text-base text-text-muted font-normal">{suffix}</span>
                </p>
              </div>
              <div className="p-1.5 sm:p-2 rounded-lg" style={{ background: `${color}15` }}>
                <Icon size={16} style={{ color }} />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* ── Progress bar ───────────────────────────────────── */}
      {total > 0 && (
        <div className="mb-5 sm:mb-6">
          <div className="flex items-center justify-between text-[11px] text-text-muted mb-1.5">
            <span>Progresso do mês</span>
            <span>{Math.round((current / total) * 100)}% concluído</span>
          </div>
          <div className="h-1.5 bg-bg-elevated rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-accent to-success rounded-full transition-all duration-700"
              style={{ width: `${(current / total) * 100}%` }} />
          </div>
        </div>
      )}

      {/* ── Filter tabs ────────────────────────────────────── */}
      <div className="flex items-center gap-1 mb-4 sm:mb-5 border-b border-border pb-3 sm:pb-4 overflow-x-auto no-scrollbar">
        {[
          { label: 'Todos', count: total },
          { label: 'Em dia', count: current },
          { label: 'Pendentes', count: pending + noData },
          { label: 'Erros', count: errors },
        ].map(({ label, count }) => (
          <button key={label}
            className="px-2.5 sm:px-3 py-1.5 rounded-lg text-[12px] font-medium text-text-secondary
              hover:text-text-primary hover:bg-bg-hover transition-all duration-150 flex items-center gap-1.5
              whitespace-nowrap flex-shrink-0">
            {label}
            <span className="text-[10px] bg-bg-elevated px-1.5 py-0.5 rounded text-text-muted">{count}</span>
          </button>
        ))}

        <div className="ml-auto flex items-center gap-2 flex-shrink-0">
          <span className="hidden sm:inline text-[11px] text-text-muted">Ordenar:</span>
          <button className="btn-ghost text-[12px] px-2 py-1 whitespace-nowrap">
            Nome <span className="text-text-muted">↑</span>
          </button>
        </div>
      </div>

      {/* ── Grid de condomínios — 1 col mobile, 2 sm, 3 md, 4 xl ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {statuses.map(status => (
          <CondoCard key={status.condominio.id} status={status} />
        ))}
      </div>
    </div>
  );
}
