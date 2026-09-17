import { NextRequest, NextResponse } from 'next/server';
import { getCondominio } from '@/lib/condominios';
import { rodarEtapaConciliacao } from '@/lib/validacaoProcessor';
import { lerStatus } from '@/lib/validacaoStorage';

export const dynamic = 'force-dynamic';
export const maxDuration = 300;

export async function POST(request: NextRequest) {
  const { condominioId, mes } = await request.json();
  if (!condominioId || !mes) {
    return NextResponse.json({ error: 'condominioId e mes são obrigatórios' }, { status: 400 });
  }
  const condo = getCondominio(condominioId);
  if (!condo) return NextResponse.json({ error: 'Condomínio não encontrado' }, { status: 404 });

  const resultado = await rodarEtapaConciliacao({ condominioId, mes, etapa: 'render' });
  if (!resultado.success) {
    return NextResponse.json({ error: resultado.error ?? 'Falha ao gerar o relatório', log: resultado.log }, { status: 500 });
  }
  const status = lerStatus(condo.pasta_dados, mes);
  return NextResponse.json({ success: true, log: resultado.log, status });
}
