import { NextRequest, NextResponse } from 'next/server';
import { writeFileSync, unlinkSync } from 'fs';
import path from 'path';
import os from 'os';
import { getCondominio } from '@/lib/condominios';
import { rodarEtapaConciliacao } from '@/lib/validacaoProcessor';
import { lerStatus } from '@/lib/validacaoStorage';

export const dynamic = 'force-dynamic';
export const maxDuration = 900;

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

    const ext = path.extname(arquivo.name) || '.pdf';
    tmpPath = path.join(os.tmpdir(), `sc_conciliacao_${Date.now()}${ext}`);
    writeFileSync(tmpPath, Buffer.from(await arquivo.arrayBuffer()));

    const resultado = await rodarEtapaConciliacao({
      condominioId, mes, etapa: 'extrair', arquivo: tmpPath,
    });
    if (!resultado.success) {
      return NextResponse.json({ error: resultado.error ?? 'Falha na extração', log: resultado.log }, { status: 500 });
    }

    const status = lerStatus(condo.pasta_dados, mes);
    return NextResponse.json({ success: true, log: resultado.log, status });
  } catch (err: any) {
    return NextResponse.json({ error: err.message ?? 'Erro interno' }, { status: 500 });
  } finally {
    if (tmpPath) { try { unlinkSync(tmpPath); } catch { /* ignore */ } }
  }
}
