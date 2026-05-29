import { NextRequest, NextResponse } from 'next/server';
import { readHistory, getImportsByCondominio } from '@/lib/history';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const condominioId = searchParams.get('condominioId');
  const limit = parseInt(searchParams.get('limit') ?? '100', 10);

  const records = condominioId
    ? getImportsByCondominio(condominioId)
    : readHistory();

  return NextResponse.json({ records: records.slice(0, limit) });
}
