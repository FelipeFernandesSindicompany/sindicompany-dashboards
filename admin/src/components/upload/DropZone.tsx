'use client';

import React, { useCallback, useState, useRef } from 'react';
import { Upload, FileText, FileSpreadsheet, X, CheckCircle2, AlertCircle, Loader2, ChevronDown, Send } from 'lucide-react';
import type { DetectedFile, Condominio } from '@/lib/types';

const MESES = [
  { value: '', label: 'Selecionar mês...' },
  ...[1,2,3,4,5,6,7,8,9,10,11,12].flatMap(m => {
    const now = new Date();
    return [-1, 0].map(offset => {
      const d = new Date(now.getFullYear(), now.getMonth() + offset - m + m, 1);
      const y = now.getFullYear() - (m > now.getMonth() + 1 ? 1 : 0);
      const mm = String(m).padStart(2, '0');
      return { value: `${y}-${mm}`, label: `${mm}/${y}` };
    });
  }).filter((v, i, a) => a.findIndex(x => x.value === v.value) === i).slice(0, 24),
];

function buildMesOptions() {
  const options = [];
  const now = new Date();
  for (let i = 0; i < 18; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    options.push({ value: `${y}-${m}`, label: `${m}/${y}` });
  }
  return options;
}

const MES_OPTIONS = buildMesOptions();

function FileTypeIcon({ type }: { type: DetectedFile['type'] }) {
  if (type === 'pdf') return <FileText size={16} className="text-red-400" />;
  if (type === 'xlsx' || type === 'xls') return <FileSpreadsheet size={16} className="text-green-400" />;
  return <FileText size={16} className="text-text-muted" />;
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

function fmtBRL(v: number): string {
  return v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

interface FileItemProps {
  file: DetectedFile;
  condominios: Condominio[];
  onUpdate: (id: string, patch: Partial<DetectedFile>) => void;
  onRemove: (id: string) => void;
  onProcess: (file: DetectedFile) => void;
}

function FileItem({ file, condominios, onUpdate, onRemove, onProcess }: FileItemProps) {
  const condoOk = !!file.detectedCondominioId;
  const mesOk = !!file.detectedMes;
  const ready = condoOk && mesOk && file.status !== 'processing' && file.status !== 'done';

  return (
    <div className={`card p-4 animate-slide-up transition-all duration-200
      ${file.status === 'done' ? 'border-success/30 bg-success/5' : ''}
      ${file.status === 'error' ? 'border-danger/30 bg-danger/5' : ''}
    `}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5 p-2 rounded-lg bg-bg-elevated border border-border flex-shrink-0">
          <FileTypeIcon type={file.type} />
        </div>

        <div className="flex-1 min-w-0">
          {/* Filename + size */}
          <div className="flex items-center justify-between gap-2 mb-2">
            <p className="text-[13px] font-medium text-text-primary truncate">{file.originalName}</p>
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="text-[11px] text-text-muted">{fmtSize(file.size)}</span>
              {file.status !== 'processing' && file.status !== 'done' && (
                <button onClick={() => onRemove(file.id)}
                  className="p-1 rounded hover:bg-bg-elevated text-text-muted hover:text-danger transition-colors">
                  <X size={12} />
                </button>
              )}
            </div>
          </div>

          {/* Detection fields */}
          <div className="grid grid-cols-2 gap-2 mb-3">
            {/* Condomínio selector */}
            <div>
              <label className="block text-[10px] text-text-muted mb-1">Condomínio</label>
              <div className="relative">
                <select
                  value={file.detectedCondominioId ?? ''}
                  onChange={e => {
                    const c = condominios.find(x => x.id === e.target.value);
                    onUpdate(file.id, {
                      detectedCondominioId: e.target.value || null,
                      detectedCondominioNome: c?.nome ?? null,
                    });
                  }}
                  disabled={file.status === 'processing' || file.status === 'done'}
                  className={`input text-[12px] pr-7 appearance-none
                    ${!condoOk ? 'border-warning/40 bg-warning/5' : 'border-success/30'}
                  `}
                >
                  <option value="">Selecionar...</option>
                  {condominios.map(c => (
                    <option key={c.id} value={c.id}>{c.nome}</option>
                  ))}
                </select>
                <ChevronDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none" />
              </div>
              {file.confidence > 0 && file.confidence < 100 && (
                <p className="text-[10px] text-text-muted mt-0.5">Confiança: {file.confidence}%</p>
              )}
            </div>

            {/* Mês selector */}
            <div>
              <label className="block text-[10px] text-text-muted mb-1">Mês de referência</label>
              <div className="relative">
                <select
                  value={file.detectedMes ?? ''}
                  onChange={e => onUpdate(file.id, { detectedMes: e.target.value || null })}
                  disabled={file.status === 'processing' || file.status === 'done'}
                  className={`input text-[12px] pr-7 appearance-none
                    ${!mesOk ? 'border-warning/40 bg-warning/5' : 'border-success/30'}
                  `}
                >
                  {MES_OPTIONS.map(o => (
                    <option key={o.value} value={o.value}>{o.label || 'Selecionar...'}</option>
                  ))}
                </select>
                <ChevronDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none" />
              </div>
            </div>
          </div>

          {/* Status / action */}
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5">
              {file.status === 'done' && (
                <span className="flex items-center gap-1 text-[11px] text-success font-medium">
                  <CheckCircle2 size={12} /> Injetado com sucesso
                </span>
              )}
              {file.status === 'error' && (
                <span className="flex items-center gap-1 text-[11px] text-danger font-medium">
                  <AlertCircle size={12} /> {file.error ?? 'Erro ao processar'}
                </span>
              )}
              {file.status === 'processing' && (
                <span className="flex items-center gap-1 text-[11px] text-accent font-medium">
                  <Loader2 size={12} className="animate-spin" /> Processando PDF... (pode levar 1-3 min)
                </span>
              )}
              {(file.status === 'ready' || file.status === 'detected') && !condoOk && (
                <span className="text-[11px] text-warning">Selecione o condomínio</span>
              )}
              {(file.status === 'ready' || file.status === 'detected') && condoOk && !mesOk && (
                <span className="text-[11px] text-warning">Selecione o mês</span>
              )}
            </div>

            {ready && (
              <button onClick={() => onProcess(file)} className="btn-primary text-[12px] px-3 py-1.5">
                <Send size={12} />
                Injetar
              </button>
            )}
          </div>

          {/* Result summary card */}
          {file.status === 'done' && file.resumo && (
            <div className="mt-3 p-3 rounded-xl bg-success/5 border border-success/20 space-y-2">
              <p className="text-[11px] font-semibold text-success">{file.resumo.tit} — {file.resumo.html}</p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
                <span className="text-text-muted">Saldo anterior</span>
                <span className="text-text-primary font-medium text-right">{fmtBRL(file.resumo.tAnt)}</span>
                <span className="text-text-muted">Créditos</span>
                <span className="text-success font-medium text-right">+{fmtBRL(file.resumo.tCred)}</span>
                <span className="text-text-muted">Débitos</span>
                <span className="text-danger font-medium text-right">-{fmtBRL(file.resumo.tDeb)}</span>
                <span className="text-text-muted font-semibold">Saldo atual</span>
                <span className="text-text-primary font-bold text-right">{fmtBRL(file.resumo.tAtual)}</span>
                <span className="text-text-muted">Inadimplência</span>
                <span className="text-warning font-medium text-right">{fmtBRL(file.resumo.inad)}</span>
              </div>
              <div className="flex items-center justify-between pt-1 border-t border-success/10">
                <span className="text-[10px] text-text-muted">{file.resumo.nContas} conta(s) · {file.resumo.nDesp} categoria(s)</span>
                <a
                  href={`/api/dashboard/${file.detectedCondominioId}`}
                  target="_blank"
                  className="text-[11px] text-accent hover:underline font-medium"
                >
                  Ver dashboard →
                </a>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

interface Props {
  condominios: Condominio[];
  onImportDone?: () => void;
}

export function DropZone({ condominios, onImportDone }: Props) {
  const [isDragging, setIsDragging] = useState(false);
  const [files, setFiles] = useState<DetectedFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(async (rawFiles: FileList | File[]) => {
    const arr = Array.from(rawFiles);
    if (!arr.length) return;

    setIsUploading(true);
    setUploadError(null);

    // Calculate total size for progress message
    const totalBytes = arr.reduce((s, f) => s + f.size, 0);
    const totalMB = (totalBytes / (1024 * 1024)).toFixed(1);
    setUploadProgress(totalBytes > 1_000_000
      ? `Enviando ${totalMB} MB... (arquivos grandes podem demorar alguns minutos via ngrok)`
      : `Enviando arquivo...`);

    // 5 min timeout for large files (PDFs de 300+ páginas podem ser grandes)
    const TIMEOUT_MS = 5 * 60 * 1000;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);

    try {
      const fd = new FormData();
      arr.forEach(f => fd.append('files', f));

      const res = await fetch('/api/upload', {
        method: 'POST',
        body: fd,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);
      setUploadProgress(null);

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
        throw new Error(err.error ?? `Erro ${res.status}`);
      }

      const data = await res.json();

      if (data.files) {
        setFiles(prev => [...prev, ...data.files]);
      } else if (data.error) {
        throw new Error(data.error);
      }
    } catch (err: any) {
      clearTimeout(timeoutId);
      setUploadProgress(null);
      const msg = err.name === 'AbortError'
        ? `Tempo esgotado (${Math.round(TIMEOUT_MS / 60000)} min). Arquivo muito grande para envio via ngrok. Tente acessar o admin direto em http://localhost:3500`
        : (err.message ?? 'Erro ao enviar arquivo');
      setUploadError(msg);
      console.error('Upload error:', err);
    } finally {
      setIsUploading(false);
    }
  }, []);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    handleFiles(e.dataTransfer.files);
  }, [handleFiles]);

  const onProcess = useCallback(async (file: DetectedFile) => {
    if (!file.detectedCondominioId || !file.detectedMes) return;

    setFiles(prev => prev.map(f => f.id === file.id ? { ...f, status: 'processing' as const } : f));

    try {
      // Trigger the processing — PDFs grandes levam até 3 min, usa AbortController longo
      const ctrl = new AbortController();
      const tid = setTimeout(() => ctrl.abort(), 5 * 60 * 1000); // 5 min
      const res = await fetch('/api/process', {
        method: 'POST',
        signal: ctrl.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fileId: file.id,
          condominioId: file.detectedCondominioId,
          mes: file.detectedMes,
          savedPath: file.savedPath,
        }),
      });
      clearTimeout(tid);
      const data = await res.json();

      if (!data.success && !data.runId) {
        setFiles(prev => prev.map(f =>
          f.id === file.id ? { ...f, status: 'error' as const, error: data.error } : f
        ));
        return;
      }

      // If runId returned, poll for completion
      if (data.runId) {
        await pollForResult(file.id, data.runId);
      } else {
        // Synchronous result (local mode)
        setFiles(prev => prev.map(f =>
          f.id === file.id
            ? { ...f, status: data.success ? 'done' as const : 'error' as const, error: data.error, resumo: data.resumo }
            : f
        ));
        if (data.success && onImportDone) onImportDone();
      }
    } catch (err: any) {
      setFiles(prev => prev.map(f =>
        f.id === file.id ? { ...f, status: 'error' as const, error: err.message } : f
      ));
    }
  }, [onImportDone]);

  const pollForResult = useCallback(async (fileId: string, runId: number) => {
    const maxAttempts = 40; // 40 × 5s = 3.3 min
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise(r => setTimeout(r, 5000));
      try {
        const res = await fetch(`/api/process/status?runId=${runId}`);
        const data = await res.json();
        if (data.done) {
          setFiles(prev => prev.map(f =>
            f.id === fileId
              ? { ...f, status: data.success ? 'done' as const : 'error' as const, error: data.error, resumo: data.resumo }
              : f
          ));
          if (data.success && onImportDone) onImportDone();
          return;
        }
      } catch {}
    }
    // Timeout
    setFiles(prev => prev.map(f =>
      f.id === fileId ? { ...f, status: 'error' as const, error: 'Tempo esgotado aguardando processamento' } : f
    ));
  }, [onImportDone]);

  const processAll = useCallback(() => {
    const ready = files.filter(f => f.detectedCondominioId && f.detectedMes && f.status === 'ready');
    ready.forEach(onProcess);
  }, [files, onProcess]);

  const readyCount = files.filter(f => f.detectedCondominioId && f.detectedMes && f.status === 'ready').length;
  const doneCount = files.filter(f => f.status === 'done').length;

  return (
    <div className="space-y-4">
      {/* Drop area */}
      <div
        onDragOver={e => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`relative flex flex-col items-center justify-center rounded-2xl border-2 border-dashed
          cursor-pointer transition-all duration-200 p-12 text-center
          ${isDragging
            ? 'border-accent bg-accent-muted scale-[1.01]'
            : 'border-border bg-bg-surface hover:border-border-focus hover:bg-bg-card'
          }
        `}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".xlsx,.xls,.pdf,.csv"
          className="hidden"
          onChange={e => e.target.files && handleFiles(e.target.files)}
        />

        <div className={`mb-4 p-4 rounded-2xl transition-all duration-200
          ${isDragging ? 'bg-accent/20 scale-110' : 'bg-bg-elevated border border-border'}`}>
          {isUploading
            ? <Loader2 size={28} className="text-accent animate-spin" />
            : <Upload size={28} className={isDragging ? 'text-accent' : 'text-text-muted'} />
          }
        </div>

        <p className="text-[15px] font-semibold text-text-primary mb-1">
          {isDragging ? 'Solte os arquivos aqui' : isUploading ? 'Enviando...' : 'Arraste os arquivos ou clique para selecionar'}
        </p>
        {isUploading && uploadProgress ? (
          <p className="text-[12px] text-accent text-center max-w-xs">{uploadProgress}</p>
        ) : (
          <p className="text-[12px] text-text-muted">
            Suportado: XLSX · XLS · PDF · CSV — múltiplos arquivos simultâneos
          </p>
        )}
      </div>

      {/* Upload error message */}
      {uploadError && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-xl border border-danger/30 bg-danger/5 text-[12px] text-danger">
          <AlertCircle size={14} className="flex-shrink-0" />
          <span>{uploadError}</span>
          <button
            onClick={() => setUploadError(null)}
            className="ml-auto p-0.5 hover:opacity-70 transition-opacity"
          >
            <X size={12} />
          </button>
        </div>
      )}

      {/* File list */}
      {files.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <h3 className="text-[13px] font-semibold text-text-primary">
                {files.length} arquivo{files.length !== 1 ? 's' : ''} carregado{files.length !== 1 ? 's' : ''}
              </h3>
              {doneCount > 0 && (
                <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-success/10 text-success border border-success/20">
                  {doneCount} injetado{doneCount !== 1 ? 's' : ''}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {readyCount > 1 && (
                <button onClick={processAll} className="btn-primary text-[12px] px-4 py-1.5">
                  <Send size={13} />
                  Injetar todos ({readyCount})
                </button>
              )}
              <button
                onClick={() => setFiles([])}
                className="btn-secondary text-[12px] px-3 py-1.5">
                Limpar
              </button>
            </div>
          </div>

          {files.map(f => (
            <FileItem
              key={f.id}
              file={f}
              condominios={condominios}
              onUpdate={(id, patch) => setFiles(prev => prev.map(x => x.id === id ? { ...x, ...patch } : x))}
              onRemove={id => setFiles(prev => prev.filter(x => x.id !== id))}
              onProcess={onProcess}
            />
          ))}
        </div>
      )}
    </div>
  );
}
