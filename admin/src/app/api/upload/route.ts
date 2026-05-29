import { NextRequest, NextResponse } from 'next/server';
import { v4 as uuidv4 } from 'uuid';
import { getCondominios } from '@/lib/condominios';
import { buildDetectedFile } from '@/lib/matcher';
import { uploadFileToGitHub } from '@/lib/github';

export const dynamic = 'force-dynamic';
// Allow large file uploads
export const maxDuration = 60;

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
      // GitHub path for temporary storage
      const githubPath = `data/uploads/${savedName}`;

      const buffer = Buffer.from(await file.arrayBuffer());

      // Upload to GitHub repo
      await uploadFileToGitHub(buffer, githubPath, `upload: ${file.name}`);

      const detectedFile = buildDetectedFile(id, file.name, githubPath, file.size, condominios);
      detected.push(detectedFile);
    }

    return NextResponse.json({ files: detected });
  } catch (err: any) {
    console.error('[upload] erro:', err?.message ?? err);
    return NextResponse.json({ error: err.message ?? 'Erro interno' }, { status: 500 });
  }
}
