import { NextRequest, NextResponse } from 'next/server';
import { getCondominio } from '@/lib/condominios';
import { lerStatus } from '@/lib/validacaoStorage';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const condominioId = request.nextUrl.searchParams.get('condominioId');
  const mes = request.nextUrl.searchParams.get('mes');
  if (!condominioId || !mes) {
    return NextResponse.json({ error: 'condominioId e mes são obrigatórios' }, { status: 400 });
  }
  const condo = getCondominio(condominioId);
  if (!condo) return NextResponse.json({ error: 'Condomínio não encontrado' }, { status: 404 });

  const status = lerStatus(condo.pasta_dados, mes);
  return NextResponse.json(status);
}
