import { NextRequest, NextResponse } from 'next/server';
import { getCondominio } from '@/lib/condominios';
import { salvarRevisados, lerStatus } from '@/lib/validacaoStorage';

export const dynamic = 'force-dynamic';

// Grava achados_revisados.json com o que o usuário preencheu na tela de
// revisão (título/parágrafo/severidade/o que verificar por achado). A
// validação de completude (nenhum "pendente" sobrando) é feita de novo pelo
// Python na etapa --etapa render, que é a fonte da verdade — aqui só
// persistimos o que a pessoa editou.
export async function POST(request: NextRequest) {
  const { condominioId, mes, revisados } = await request.json();
  if (!condominioId || !mes || !Array.isArray(revisados)) {
    return NextResponse.json({ error: 'condominioId, mes e revisados[] são obrigatórios' }, { status: 400 });
  }
  const condo = getCondominio(condominioId);
  if (!condo) return NextResponse.json({ error: 'Condomínio não encontrado' }, { status: 404 });

  const resultado = salvarRevisados(condo.pasta_dados, mes, revisados);
  if (!resultado.ok) return NextResponse.json({ error: resultado.erro }, { status: 400 });

  const status = lerStatus(condo.pasta_dados, mes);
  return NextResponse.json({ success: true, status });
}
