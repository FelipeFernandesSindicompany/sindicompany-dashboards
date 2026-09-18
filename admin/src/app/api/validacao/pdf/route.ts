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
  // "Validação Balancete - <Nome do Condomínio> MM.AAAA.pdf" — mesmo padrão
  // usado por scripts/gerar_relatorio_conciliacao.py::_nome_arquivo_relatorio
  // (a barra de "MM/AAAA" vira ponto, "/" não é permitido em nome de arquivo).
  const [ano, mesNum] = mes.split('-');
  const nomeArquivo = `Validação Balancete - ${condo.nome} ${mesNum}.${ano}.pdf`;
  // filename= (fallback ASCII) + filename*= (UTF-8, RFC 5987) — acentos em
  // "Validação"/nomes de condomínio não sobrevivem no filename= puro.
  const nomeAscii = nomeArquivo.replace(/[^\x20-\x7E]/g, '_');
  return new NextResponse(buffer, {
    headers: {
      'Content-Type': 'application/pdf',
      'Content-Disposition':
        `inline; filename="${nomeAscii}"; filename*=UTF-8''${encodeURIComponent(nomeArquivo)}`,
    },
  });
}
