import { NextRequest, NextResponse } from 'next/server';
import { getCondominio } from '@/lib/condominios';
import { extractBAL, extractBALEntry } from '@/lib/htmlExtractor';

export const dynamic = 'force-dynamic';

const MONTH_ABBR = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];

export async function GET(request: NextRequest) {
  const condominioId = request.nextUrl.searchParams.get('condominioId');
  const mes = request.nextUrl.searchParams.get('mes'); // formato: 2026-06

  if (!condominioId || !mes) {
    return NextResponse.json({ error: 'condominioId e mes são obrigatórios' }, { status: 400 });
  }

  const condo = getCondominio(condominioId);
  if (!condo) {
    return NextResponse.json({ error: `Condomínio '${condominioId}' não encontrado` }, { status: 404 });
  }

  // "2026-06" → "jun26"
  const parts = mes.split('-');
  if (parts.length !== 2) {
    return NextResponse.json({ error: 'Formato de mês inválido. Use YYYY-MM' }, { status: 400 });
  }
  const monthKey = MONTH_ABBR[parseInt(parts[1]) - 1] + parts[0].slice(2);

  const bal = extractBAL(condo.html_file);
  if (!bal) {
    return NextResponse.json({ exists: false, monthKey, error: 'Dashboard HTML não encontrado ou sem dados' });
  }

  const exists = bal.allKeys.includes(monthKey);

  // Para o mês verificado, extrair todos os campos do BAL (não só tAtual/tit)
  const entryData = exists
    ? (extractBALEntry(condo.html_file, monthKey) ?? bal.data)
    : {};

  return NextResponse.json({
    exists,
    monthKey,
    allKeys: bal.allKeys,
    lastKey: bal.lastKey,
    lastMonth: bal.lastMonth,
    ...(exists ? {
      tit:      entryData.tit     ?? bal.data.tit,
      tAtual:   entryData.tAtual  ?? bal.data.tAtual,
      tAnt:     entryData.tAnt    ?? 0,
      tCred:    entryData.tCred   ?? 0,
      tDeb:     entryData.tDeb    ?? 0,
      inad:     entryData.inad    ?? 0,
      nContas:  entryData.nContas ?? 0,
      nDesp:    entryData.nDesp   ?? 0,
    } : {}),
  });
}
