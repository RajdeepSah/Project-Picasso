import { useEffect, useRef, useState } from 'react';
import { FileUp, X } from 'lucide-react';
import type { DrawingDraft } from '../api/contracts';
import { importDrawing } from '../api/client';

export function ImportDialog({ close, imported }: { close: () => void; imported: (draft: DrawingDraft) => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const abort = useRef<AbortController | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dialect, setDialect] = useState<'linear-mm' | 'picasso' | 'picasso-json'>('linear-mm');
  const [center, setCenter] = useState(false);
  const [width, setWidth] = useState('');
  const [height, setHeight] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { ref.current?.showModal(); return () => abort.current?.abort(); }, []);
  const run = async () => {
    if (!file) return;
    if (file.size > 8_000_000) { setError('File exceeds the 8 MB import limit.'); return; }
    setBusy(true); setError(''); abort.current = new AbortController();
    try {
      const result = await importDrawing({ filename: file.name, content: await file.text(), dialect,
        center_on_origin: center, fit_width_mm: width ? Number(width) : null, fit_height_mm: height ? Number(height) : null }, abort.current.signal);
      if (!abort.current.signal.aborted) imported(result);
    } catch (error) { if (!abort.current?.signal.aborted) setError(error instanceof Error ? error.message : 'Import failed.'); }
    finally { setBusy(false); }
  };
  return <dialog ref={ref} onCancel={close} className="studio-dialog" aria-labelledby="import-title"><div className="dialog-top"><span className="eyebrow">BRING YOUR OWN PATHS</span><button className="icon-button" aria-label="Close import" onClick={close}><X size={18} /></button></div><h2 id="import-title">Import a drawing</h2><p>Normalize supported G-code or a Picasso draft into a new saved drawing. Originals stay unchanged.</p>
    <label className="form-field">Drawing file<input type="file" accept=".nc,.gcode,.txt,.json" aria-label="Drawing file" onChange={event => { const selected = event.target.files?.[0] ?? null; setFile(selected); if (selected?.name.endsWith('.json')) setDialect('picasso-json'); }} /></label>
    <label className="form-field">Input format<select value={dialect} onChange={event => setDialect(event.target.value as typeof dialect)} aria-label="Import format"><option value="linear-mm">Legacy / absolute-mm linear G-code</option><option value="picasso">Strict Picasso G-code</option><option value="picasso-json">Picasso JSON draft</option></select></label>
    <label className="checkbox-control"><input type="checkbox" checked={center} onChange={event => setCenter(event.target.checked)} />Center drawing at (0,0) explicitly</label>
    <div className="form-grid"><label className="form-field">Fit width mm (optional)<input type="number" min="0.001" max="2000" value={width} onChange={event => setWidth(event.target.value)} aria-label="Import fit width" /></label><label className="form-field">Fit height mm (optional)<input type="number" min="0.001" max="2000" value={height} onChange={event => setHeight(event.target.value)} aria-label="Import fit height" /></label></div>
    <div className="notice"><p>Coordinates are preserved unless you choose centering/fit. Comments and feed words are removed; Z sign controls pen state. Arcs, relative/inch modes and unsupported commands are rejected. The new preview shows the normalized output.</p></div>
    {error && <p className="form-error" role="alert">{error}</p>}<button className="primary-button dialog-done" disabled={!file || busy} onClick={() => void run()}><FileUp size={16} />{busy ? 'Importing…' : 'Import & save drawing'}</button>
  </dialog>;
}
