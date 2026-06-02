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

    // Regra de negócio: prestações de contas chegam com 2 meses de defasagem.
    // Em junho/2026 o mês esperado (mais recente disponível) é abril/2026.
    // Dashboard com lastKey === expectedMonth → "current" (atualizado) ✓
    const abbrs = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];

    const currentMonth = (() => {
      const now = new Date();
      return `${abbrs[now.getMonth()]}${String(now.getFullYear()).slice(2)}`;
    })();

    const expectedMonth = (() => {
      const now = new Date();
      // 2 meses atrás
      const d = new Date(now.getFullYear(), now.getMonth() - 2, 1);
      return `${abbrs[d.getMonth()]}${String(d.getFullYear()).slice(2)}`;
    })();

    const statuses: CondominioStatus[] = condominios.map(condo => {
      const bal = extractBAL(condo.html_file);
      const lastImport = lastImports[condo.id] ?? null;

      let status: CondominioStatus['status'] = 'no_data';
      if (bal) {
        if (bal.lastKey === expectedMonth) status = 'current';
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

    return NextResponse.json({ statuses, currentMonth, expectedMonth });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
