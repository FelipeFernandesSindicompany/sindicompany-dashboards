import { NextRequest, NextResponse } from 'next/server';
import { writeFileSync, unlinkSync } from 'fs';
import path from 'path';
import os from 'os';
import { getCondominio } from '@/lib/condominios';
import { iniciarJobValidacao, condominioSuportado } from '@/lib/validacaoProcessor';

export const dynamic = 'force-dynamic';
export const maxDuration = 300;

export async function POST(request: NextRequest) {
  let tmpPath: string | null = null;
  try {
    const formData = await request.formData();
    const condominioId = String(formData.get('condominioId') ?? '');
    const mes = String(formData.get('mes') ?? '');
    const arquivo = formData.get('arquivo') as File | null;

    if (!condominioId || !mes || !arquivo) {
      return NextResponse.json({ error: 'condominioId, mes e arquivo são obrigatórios' }, { status: 400 });
    }
    const condo = getCondominio(condominioId);
    if (!condo) return NextResponse.json({ error: 'Condomínio não encontrado' }, { status: 404 });
    if (!condominioSuportado(condo)) {
      return NextResponse.json({ error: `Este condomínio (${condo.empresa_gestora}) ainda não tem conciliador implementado` }, { status: 400 });
    }

    const ext = path.extname(arquivo.name) || '.pdf';
    tmpPath = path.join(os.tmpdir(), `sc_conciliacao_${Date.now()}${ext}`);
    writeFileSync(tmpPath, Buffer.from(await arquivo.arrayBuffer()));

    // Roda em segundo plano (extrair + interpretar) e responde na hora; a página acompanha por /api/validacao/status.
    const inicio = iniciarJobValidacao({ condominioId, mes, arquivoTmp: tmpPath });
    if (!inicio.ok) return NextResponse.json({ error: inicio.erro }, { status: 409 });
    const emSegundoPlano = tmpPath;
    tmpPath = null;      // o job apaga o arquivo temporário ao terminar
    void emSegundoPlano;
    return NextResponse.json({ success: true, iniciado: true }, { status: 202 });
  } catch (err: any) {
    return NextResponse.json({ error: err.message ?? 'Erro interno' }, { status: 500 });
  } finally {
    if (tmpPath) { try { unlinkSync(tmpPath); } catch { /* ignore */ } }
  }
}
