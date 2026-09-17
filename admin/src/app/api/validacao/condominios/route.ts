import { NextResponse } from 'next/server';
import { getCondominios } from '@/lib/condominios';
import { EMPRESAS_COM_CONCILIACAO } from '@/lib/validacaoProcessor';

export const dynamic = 'force-dynamic';

// Lista TODOS os condomínios ativos (mesmo conjunto da aba "Visão Geral"),
// marcando quais já têm conciliador implementado
// (conciliacao/__init__.py::CONCILIADORES) — os demais aparecem na lista
// mas desabilitados, com "em breve", em vez de somem do menu.
export async function GET() {
  const condominios = getCondominios()
    .map(c => ({
      id: c.id,
      nome: c.nome,
      cor: c.cor,
      empresa_gestora: c.empresa_gestora,
      pasta_dados: c.pasta_dados,
      suportado: EMPRESAS_COM_CONCILIACAO.includes(c.empresa_gestora),
    }))
    .sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR', { sensitivity: 'base' }));
  return NextResponse.json({ condominios });
}
