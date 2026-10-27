import { useEffect, useRef, useState, type DragEvent } from 'react';
import { FileCode2, ImagePlus, Upload, X } from 'lucide-react';
import type { DrawingDraft, ImportRequest } from '../api/contracts';
import { importDrawing } from '../api/client';
import { paperSize, type PaperId } from './DrawingPreview';

type Kind = NonNullable<ImportRequest['kind']>;
type Detail = NonNullable<ImportRequest['detail']>;
const kinds: [Kind, string][] = [['image', 'Image'], ['gcode', 'G-code']];
const details: [Detail, string, string][] = [
  ['low', 'Low', 'Simple outlines and fewer lines. Fastest to draw.'],
  ['medium', 'Medium', 'Balanced detail and drawing time.'],
  ['high', 'High', 'Finer edges and patterns. Takes longest to draw.'],
];
const accept: Record<Kind, string> = { image: 'image/png,image/jpeg,image/webp,image/bmp,image/tiff', gcode: '.gcode,.nc,.ngc,.tap,.txt' };
const limit: Record<Kind, number> = { image: 8_000_000, gcode: 2_000_000 };
const isImage = (file: File) => file.type.startsWith('image/') || /\.(png|jpe?g|webp|bmp|tiff?)$/i.test(file.name);
const size = (bytes: number) => bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} KB`;

/** Base64 without the data-URL prefix. FileReader encodes off the main thread. */
const base64 = (file: File) => new Promise<string>((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).slice(String(reader.result).indexOf(',') + 1));
  reader.onerror = () => reject(new Error('The file could not be read.'));
  reader.readAsDataURL(file);
});

export function ImportDialog({ paper, close, imported }: { paper: PaperId; close: () => void; imported: (draft: DrawingDraft) => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const abort = useRef<AbortController | null>(null);
  const [kind, setKind] = useState<Kind>('image');
  const [file, setFile] = useState<File | null>(null);
  const [thumbnail, setThumbnail] = useState('');
  const [detail, setDetail] = useState<Detail>('medium');
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { ref.current?.showModal(); return () => abort.current?.abort(); }, []);
  useEffect(() => () => { if (thumbnail) URL.revokeObjectURL(thumbnail); }, [thumbnail]);

  const choose = (selected: File | null | undefined) => {
    if (!selected || busy) return;
    const next: Kind = isImage(selected) ? 'image' : 'gcode';
    setKind(next); setError('');
    if (selected.size > limit[next]) { setFile(null); setThumbnail(''); setError(`${next === 'image' ? 'Images' : 'G-code files'} must be ${size(limit[next])} or smaller.`); return; }
    setFile(selected); setThumbnail(next === 'image' ? URL.createObjectURL(selected) : '');
  };
  const switchKind = (next: Kind) => { if (next !== kind) { setKind(next); setFile(null); setThumbnail(''); setError(''); } };
  const drop = (event: DragEvent) => { event.preventDefault(); setDragging(false); choose(event.dataTransfer.files[0]); };
  const run = async () => {
    if (!file) return;
    setBusy(true); setError(''); abort.current = new AbortController();
    try {
      // Images are centred and fitted to the page (85% of it, leaving a margin); G-code keeps its own coordinates.
      const page = paperSize(paper);
      const request: ImportRequest = kind === 'image'
        ? { filename: file.name, kind, detail, content: await base64(file), fit_width_mm: page ? page[0] * .85 : null, fit_height_mm: page ? page[1] * .85 : null }
        : { filename: file.name, kind, content: await file.text() };
      const result = await importDrawing(request, abort.current.signal);
      if (!abort.current.signal.aborted) imported(result);
    } catch (error) { if (!abort.current?.signal.aborted) setError(error instanceof Error ? error.message : 'Import failed.'); }
    finally { setBusy(false); }
  };
  const hint = details.find(([value]) => value === detail)?.[2];

  return <dialog ref={ref} onCancel={close} className="studio-dialog import-dialog" aria-labelledby="import-title">
    <div className="dialog-top"><span className="eyebrow">IMPORT</span><button className="icon-button" aria-label="Close import" onClick={close}><X size={18} /></button></div>
    <h2 id="import-title">Import a drawing</h2>
    <div className="import-kinds" role="radiogroup" aria-label="Import type">{kinds.map(([value, label]) =>
      <button key={value} type="button" role="radio" aria-checked={kind === value} disabled={busy} onClick={() => switchKind(value)}>
        {value === 'image' ? <ImagePlus size={17} /> : <FileCode2 size={17} />}{label}</button>)}</div>
    <label className={`drop-zone ${dragging ? 'dragging' : ''} ${file ? 'filled' : ''}`} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}>
      <input type="file" accept={accept[kind]} aria-label="Drawing file" disabled={busy} onChange={event => { choose(event.target.files?.[0]); event.target.value = ''; }} />
      {thumbnail ? <img src={thumbnail} alt="" className="drop-thumbnail" /> : file ? <FileCode2 size={30} strokeWidth={1.5} /> : <Upload size={26} strokeWidth={1.6} />}
      {file ? <span className="drop-title">{file.name}</span>
        : <span className="drop-title">Drop {kind === 'image' ? 'an image' : 'a G-code file'} or <u>browse</u></span>}
      <span className="drop-hint">{file ? `${size(file.size)} · choose another` : kind === 'image' ? 'PNG, JPG, WEBP, BMP or TIFF · up to 8 MB' : '.gcode, .nc or .txt · up to 2 MB'}</span>
    </label>
    {kind === 'image' && <fieldset className="import-detail" disabled={busy}><legend>Detail</legend>
      <div className="import-detail-options">{details.map(([value, label]) => <label key={value} className={detail === value ? 'checked' : ''}>
        <input type="radio" name="import-detail" value={value} checked={detail === value} onChange={() => setDetail(value)} /><span>{label}</span></label>)}</div>
      <p className="import-detail-hint">{hint}</p></fieldset>}
    {error && <p className="form-error" role="alert">{error}</p>}
    <button className="primary-button dialog-done" disabled={!file || busy} onClick={() => void run()}>
      {busy ? <><span className="spinner" />{kind === 'image' ? 'Tracing image…' : 'Reading G-code…'}</> : 'Import'}</button>
  </dialog>;
}
