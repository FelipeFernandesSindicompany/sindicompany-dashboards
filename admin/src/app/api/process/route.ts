import { NextRequest, NextResponse } from 'next/server';
import { v4 as uuidv4 } from 'uuid';
import { injectarMes } from '@/lib/processor';
import { appendHistory } from '@/lib/history';
import { getCondominio } from '@/lib/condominios';
import type { ProcessRequest } from '@/lib/types';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as ProcessRequest;
    const { condominioId, mes, savedPath } = body;

    if (!condominioId || !mes || !savedPath) {
      return NextResponse.json({ error: 'Parâmetros inválidos' }, { status: 400 });
    }

    const condo = getCondominio(condominioId);
    if (!condo) {
      return NextResponse.json({ error: `Condomínio '${condominioId}' não encontrado` }, { status: 404 });
    }

    // Validate mes format
    if (!/^\d{4}-\d{2}$/.test(mes)) {
      return NextResponse.json({ error: 'Formato de mês inválido. Use YYYY-MM' }, { status: 400 });
    }

    const result = await injectarMes(condominioId, mes, savedPath);

    const record = {
      id: uuidv4(),
      timestamp: new Date().toISOString(),
      condominioId,
      condominioNome: condo.nome,
      mes,
      arquivo: savedPath.split(/[/\\]/).pop() ?? savedPath,
      status: result.success ? 'success' as const : 'error' as const,
      operador: 'admin',
      log: result.log,
      error: result.error,
    };

    appendHistory(record);

    const resumoLine = result.log.find(l => l.includes('[RESUMO]'));
    const resumo = resumoLine
      ? (() => { try { return JSON.parse(resumoLine.split('[RESUMO]')[1].trim()); } catch { return null; } })()
      : null;

    return NextResponse.json({ success: result.success, log: result.log, record, resumo });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
