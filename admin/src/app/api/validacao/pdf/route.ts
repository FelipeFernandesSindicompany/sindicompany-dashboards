import { NextRequest, NextResponse } from 'next/server';
import { readFileSync } from 'fs';
import { getCondominio } from '@/lib/condominios';
import { caminhoRelatorio } from '@/lib/validacaoStorage';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const condominioId = request.nextUrl.searchParams.get('condominioId');
  const mes = request.nextUrl.searchParams.get('mes');
  if (!condominioId || !mes) {
    return NextResponse.json({ error: 'condominioId e mes são obrigatórios' }, { status: 400 });
  }
  const condo = getCondominio(condominioId);
  if (!condo) return NextResponse.json({ error: 'Condomínio não encontrado' }, { status: 404 });

  const pdfPath = caminhoRelatorio(condo.pasta_dados, mes);
  if (!pdfPath) return NextResponse.json({ error: 'Relatório ainda não foi gerado' }, { status: 404 });

  const buffer = readFileSync(pdfPath);
  return new NextResponse(buffer, {
    headers: {
      'Content-Type': 'application/pdf',
      'Content-Disposition': `inline; filename="relatorio_validacao_${condominioId}_${mes}.pdf"`,
    },
  });
}
