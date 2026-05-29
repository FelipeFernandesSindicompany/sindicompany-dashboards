import { NextResponse } from 'next/server';
import { getCondominios } from '@/lib/condominios';
import { extractBAL } from '@/lib/htmlExtractor';
import { readHistoryAsync } from '@/lib/history';
import type { CondominioStatus, ImportRecord } from '@/lib/types';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const condominios = getCondominios();
    const allRecords = await readHistoryAsync();

    // Build lastImports map (newest-first is preserved by readHistoryAsync)
    const lastImports: Record<string, ImportRecord> = {};
    for (const r of allRecords) {
      if (!lastImports[r.condominioId]) {
        lastImports[r.condominioId] = r;
      }
    }

    const currentMonth = (() => {
      const now = new Date();
      const abbrs = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
      return `${abbrs[now.getMonth()]}${String(now.getFullYear()).slice(2)}`;
    })();

    const statuses: CondominioStatus[] = condominios.map(condo => {
      const bal = extractBAL(condo.html_file);
      const lastImport = lastImports[condo.id] ?? null;

      let status: CondominioStatus['status'] = 'no_data';
      if (bal) {
        if (bal.lastKey === currentMonth) status = 'current';
        else status = 'pending';
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

    return NextResponse.json({ statuses, currentMonth });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
