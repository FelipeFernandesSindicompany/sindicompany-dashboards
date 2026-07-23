import { NextResponse } from 'next/server';
import { getCondominios } from '@/lib/condominios';
import { extractBAL } from '@/lib/htmlExtractor';
import { readHistoryAsync } from '@/lib/history';
import type { CondominioStatus, ImportRecord } from '@/lib/types';

export const dynamic = 'force-dynamic';

const abbrs = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];

function monthKeyToNum(key: string): number {
  const m = abbrs.indexOf(key.slice(0, 3));
  const y = parseInt(key.slice(3), 10);
  return y * 12 + m;
}

/** Até o dia 14 → 2 meses atrás; a partir do dia 15 → 1 mês atrás */
function getMonthsBack(): number {
  return new Date().getDate() >= 15 ? 1 : 2;
}

function getExpectedMonth(): string {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - getMonthsBack(), 1);
  return `${abbrs[d.getMonth()]}${String(d.getFullYear()).slice(2)}`;
}

export async function GET() {
  try {
    const condominios = getCondominios();
    const allRecords = await readHistoryAsync();

    const lastImports: Record<string, ImportRecord> = {};
    for (const r of allRecords) {
      if (!lastImports[r.condominioId]) {
        lastImports[r.condominioId] = r;
      }
    }

    const currentMonth = `${abbrs[new Date().getMonth()]}${String(new Date().getFullYear()).slice(2)}`;
    const expectedMonth = getExpectedMonth();
    const expectedNum   = monthKeyToNum(expectedMonth);

    const statuses: CondominioStatus[] = condominios.map(condo => {
      const bal = extractBAL(condo.html_file);
      const lastImport = lastImports[condo.id] ?? null;

      let status: CondominioStatus['status'] = 'no_data';
      if (bal) {
        // "Em dia" se o dashboard tem dados do mês esperado OU mais recente
        status = monthKeyToNum(bal.lastKey) >= expectedNum ? 'current' : 'pending';
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
    });

    return NextResponse.json({ statuses, currentMonth, expectedMonth });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
