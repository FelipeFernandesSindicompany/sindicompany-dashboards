import { NextRequest, NextResponse } from 'next/server';
import { writeFileSync, mkdirSync, existsSync } from 'fs';
import path from 'path';
import { v4 as uuidv4 } from 'uuid';
import { UPLOADS_DIR } from '@/lib/paths';
import { getCondominios } from '@/lib/condominios';
import { buildDetectedFile } from '@/lib/matcher';

export const dynamic = 'force-dynamic';
export const maxDuration = 60;

// Modo: 'cloud' quando GITHUB_TOKEN está definido (Vercel), 'local' caso contrário
const IS_CLOUD = !!process.env.GITHUB_TOKEN;

export async function POST(request: NextRequest) {
  try {
    if (request.signal?.aborted) {
      return NextResponse.json({ error: 'Requisição cancelada' }, { status: 499 });
    }

    let formData: FormData;
    try {
      formData = await request.formData();
    } catch (parseErr: any) {
      if (parseErr?.code === 'ECONNRESET' || parseErr?.message?.includes('aborted')) {
        return NextResponse.json({ error: 'Upload cancelado pelo cliente' }, { status: 499 });
      }
      throw parseErr;
    }

    const files = formData.getAll('files') as File[];
    if (!files.length) {
      return NextResponse.json({ error: 'Nenhum arquivo enviado' }, { status: 400 });
    }

    const condominios = getCondominios();
    const detected = [];

    for (const file of files) {
      const id = uuidv4();
      const ext = file.name.split('.').pop() ?? 'bin';
      const savedName = `${id}.${ext}`;
      const buffer = Buffer.from(await file.arrayBuffer());

      let savedPath: string;

      if (IS_CLOUD) {
        // ── Modo Vercel: salva no repositório GitHub ──────────────────────
        const { uploadFileToGitHub } = await import('@/lib/github');
        savedPath = `data/uploads/${savedName}`;
        await uploadFileToGitHub(buffer, savedPath, `upload: ${file.name}`);
      } else {
        // ── Modo Local: salva no disco (ngrok / PM2 local) ────────────────
        if (!existsSync(UPLOADS_DIR)) mkdirSync(UPLOADS_DIR, { recursive: true });
        savedPath = path.join(UPLOADS_DIR, savedName);
        writeFileSync(savedPath, buffer);
      }

      const detectedFile = buildDetectedFile(id, file.name, savedPath, file.size, condominios);
      detected.push(detectedFile);
    }

    return NextResponse.json({ files: detected });
  } catch (err: any) {
    console.error('[upload] erro:', err?.message ?? err);
    return NextResponse.json({ error: err.message ?? 'Erro interno' }, { status: 500 });
  }
}
