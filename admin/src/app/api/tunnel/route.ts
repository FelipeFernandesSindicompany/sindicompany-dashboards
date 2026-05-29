import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { PROJECT_ROOT } from '@/lib/paths';

export const dynamic = 'force-dynamic';

const URL_FILE = path.join(PROJECT_ROOT, 'data', 'tunnel_url.txt');

export async function GET() {
  try {
    const url = fs.readFileSync(URL_FILE, 'utf8').trim();
    return NextResponse.json({ url: url || null });
  } catch {
    return NextResponse.json({ url: null });
  }
}
