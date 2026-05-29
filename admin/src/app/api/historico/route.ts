import { NextRequest, NextResponse } from 'next/server';
import { readHistoryAsync } from '@/lib/history';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const condominioId = searchParams.get('condominioId');
  const limit = parseInt(searchParams.get('limit') ?? '100', 10);

  const all = await readHistoryAsync();
  const records = condominioId
    ? all.filter(r => r.condominioId === condominioId)
    : all;

  return NextResponse.json({ records: records.slice(0, limit) });
}
