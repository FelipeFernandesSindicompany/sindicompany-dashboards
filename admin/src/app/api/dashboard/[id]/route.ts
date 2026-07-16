import { NextRequest, NextResponse } from 'next/server';
import { readFileSync, existsSync } from 'fs';
import path from 'path';
import { DOCS_DIR } from '@/lib/paths';
import { getCondominio } from '@/lib/condominios';

export const dynamic = 'force-dynamic';

const GITHUB_PAGES_BASE =
  'https://felipefernandessindicompany.github.io/sindicompany-dashboards';

export async function GET(
  _request: NextRequest,
  { params }: { params: { id: string } }
) {
  const condo = getCondominio(params.id);
  if (!condo) {
    return new NextResponse('Condomínio não encontrado', { status: 404 });
  }

  // No Vercel: serve o dashboard diretamente do GitHub Pages
  if (process.env.VERCEL || process.env.GITHUB_TOKEN) {
    const githubUrl = `${GITHUB_PAGES_BASE}/${condo.html_file}`;
    try {
      const res = await fetch(githubUrl, { next: { revalidate: 60 } });
      if (res.ok) {
        const html = await res.text();
        return new NextResponse(html, {
          headers: { 'Content-Type': 'text/html; charset=utf-8' },
        });
      }
    } catch { /* fall through */ }
    // Se GitHub Pages ainda não estiver ativo, redireciona
    return NextResponse.redirect(githubUrl, { status: 302 });
  }

  // Local: lê do disco
  const htmlPath = path.join(DOCS_DIR, condo.html_file);
  if (!existsSync(htmlPath)) {
    return new NextResponse('Dashboard HTML não encontrado', { status: 404 });
  }
  const html = readFileSync(htmlPath, 'utf-8');
  return new NextResponse(html, {
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
    },
  });
}
