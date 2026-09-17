import { NextResponse } from 'next/server';
import { getCondominios } from '@/lib/condominios';
import { EMPRESAS_COM_CONCILIACAO } from '@/lib/validacaoProcessor';

export const dynamic = 'force-dynamic';

// Só lista condomínios cuja administradora já tem um conciliador implementado
// (conciliacao/__init__.py::CONCILIADORES) — os demais aparecem em breve.
export async function GET() {
  const condominios = getCondominios()
    .filter(c => EMPRESAS_COM_CONCILIACAO.includes(c.empresa_gestora))
    .map(c => ({ id: c.id, nome: c.nome, cor: c.cor, empresa_gestora: c.empresa_gestora, pasta_dados: c.pasta_dados }));
  return NextResponse.json({ condominios });
}
