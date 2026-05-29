import { NextRequest, NextResponse } from 'next/server';
import { readFileSync, existsSync } from 'fs';
import path from 'path';
import { DOCS_DIR } from '@/lib/paths';
import { getCondominio } from '@/lib/condominios';

export const dynamic = 'force-dynamic';

export async function GET(
  _request: NextRequest,
  { params }: { params: { id: string } }
) {
  const condo = getCondominio(params.id);
  if (!condo) {
    return new NextResponse('Condomínio não encontrado', { status: 404 });
  }

  const htmlPath = path.join(DOCS_DIR, condo.html_file);
  if (!existsSync(htmlPath)) {
    return new NextResponse('Dashboard HTML não encontrado', { status: 404 });
  }

  const html = readFileSync(htmlPath, 'utf-8');
  return new NextResponse(html, {
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'X-Frame-Options': 'SAMEORIGIN',
    },
  });
}
