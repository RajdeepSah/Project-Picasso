import { ArrowDownToLine, ArrowRight, LockKeyhole, RotateCcw, ShieldCheck } from 'lucide-react';
import type { DrawingDraft, DrawingSpec, RevisionRequest } from '../api/contracts';

export type Edits = {
  width: string; height: string; rotation: string; x: string; y: string;
  seed: string; detail: DrawingSpec['detail']; petals: string; turns: string; symmetry: string;
};
export function fieldsFor(draft: DrawingDraft): Edits {
  return { width: String(draft.spec.dimensions.width_mm), height: String(draft.spec.dimensions.height_mm),
    rotation: String(draft.transform.rotation_degrees ?? 0), x: String(draft.transform.offset_x_mm ?? 0), y: String(draft.transform.offset_y_mm ?? 0),
    seed: String(draft.spec.seed ?? 0), detail: draft.spec.detail ?? 'standard', petals: String(draft.spec.parameters?.petals ?? draft.spec.parameters?.symmetry ?? 12),
    turns: String(draft.spec.parameters?.turns ?? (draft.spec.detail === 'dense' ? 6 : draft.spec.detail === 'sparse' ? 4 : 5)),
    symmetry: String(draft.spec.parameters?.symmetry ?? 8) };
}
export const emptyEdits: Edits = { width: '120', height: '120', rotation: '0', x: '0', y: '0', seed: '0', detail: 'standard', petals: '12', turns: '5', symmetry: '8' };

export function revisionPayload(draft: DrawingDraft, fields: Edits): RevisionRequest {
  for (const [key, value] of Object.entries(fields)) {
    if (key !== 'detail' && (!value?.trim() || !Number.isFinite(Number(value)))) throw new Error('Enter finite numbers for drawing controls.');
  }
  const width = Number(fields.width), height = Number(fields.height), seed = Number(fields.seed);
  if (width <= 0 || height <= 0 || width > 2000 || height > 2000) throw new Error('Dimensions must be positive and no larger than 2000 mm.');
  if (!Number.isInteger(seed) || seed < 0 || seed > 4294967295) throw new Error('Seed must be a whole number from 0 to 4294967295.');
  const parameters = { ...draft.spec.parameters, radius_mm: null };
  if (draft.spec.generator === 'mandala') { parameters.petals = Number(fields.petals); parameters.symmetry = null; }
  if (draft.spec.generator === 'pattern') parameters.symmetry = Number(fields.symmetry);
  if (draft.spec.generator === 'spiral') parameters.turns = Number(fields.turns);
  return { spec: { ...draft.spec, dimensions: { width_mm: width, height_mm: height }, seed, detail: fields.detail, parameters },
    transform: { ...draft.transform, rotation_degrees: Number(fields.rotation), offset_x_mm: Number(fields.x), offset_y_mm: Number(fields.y) } };
}

export function DrawingInspector({ draft, fields, change, busy, available, dirty, aspectLocked, setAspectLocked,
  seedLocked, setSeedLocked, regenerate, download }: {
  draft: DrawingDraft | null; fields: Edits; change: (key: keyof Edits, value: string) => void;
  busy: boolean; available: boolean; dirty: boolean; aspectLocked: boolean; setAspectLocked: (value: boolean) => void;
  seedLocked: boolean; setSeedLocked: (value: boolean) => void; regenerate: () => void;
  download: (format: 'json' | 'svg' | 'gcode') => void;
}) {
  return <div className="inspector-body drawing-controls">
    <div className="section-heading"><h3>Make it your own</h3><span className="small-tag">{draft ? `REV ${draft.revision}` : 'OFFLINE'}</span></div>
    <p className="muted-copy">{draft ? 'Adjustments update the exported path automatically.' : 'Generate a drawing to explore its dimensions and paths.'}</p>
    <fieldset disabled={!draft || !available}><legend>Fit dimensions <span>mm</span></legend>
      <div className="dimension-fields"><label>W<input type="number" min="0.1" max="2000" step="0.1" value={fields.width} onChange={e => change('width', e.target.value)} aria-label="Drawing width in millimetres" /></label><span>×</span><label>H<input type="number" min="0.1" max="2000" step="0.1" value={fields.height} onChange={e => change('height', e.target.value)} aria-label="Drawing height in millimetres" /></label></div>
      <label className="checkbox-control"><input type="checkbox" checked={aspectLocked} onChange={e => setAspectLocked(e.target.checked)} /><LockKeyhole size={12} /> Lock aspect ratio</label>
      <div className="transform-fields"><label>Rotation °<input type="number" min="-360" max="360" value={fields.rotation} onChange={e => change('rotation', e.target.value)} aria-label="Drawing rotation in degrees" /></label><label>Center X mm<input type="number" min="-2000" max="2000" value={fields.x} onChange={e => change('x', e.target.value)} aria-label="Drawing center X" /></label><label>Center Y mm<input type="number" min="-2000" max="2000" value={fields.y} onChange={e => change('y', e.target.value)} aria-label="Drawing center Y" /></label></div>
      <label className="control-label">Detail level<select aria-label="Drawing detail level" value={fields.detail} onChange={e => change('detail', e.target.value)}><option value="sparse">Simple</option><option value="standard">Standard</option><option value="dense">Intricate</option></select></label>
      {draft?.spec.generator === 'mandala' && <label className="control-label seed-field">Petals<input type="number" min="3" max="64" value={fields.petals} onChange={e => change('petals', e.target.value)} aria-label="Mandala petals" /></label>}
      {draft?.spec.generator === 'spiral' && <label className="control-label seed-field">Turns<input type="number" min="0.1" max="100" step="0.1" value={fields.turns} onChange={e => change('turns', e.target.value)} aria-label="Spiral turns" /></label>}
      {draft?.spec.generator === 'pattern' && <label className="control-label seed-field">Symmetry<input type="number" min="2" max="64" value={fields.symmetry} onChange={e => change('symmetry', e.target.value)} aria-label="Pattern symmetry" /></label>}
      <label className="control-label seed-field">Variation seed<input type="number" min="0" max="4294967295" value={fields.seed} onChange={e => change('seed', e.target.value)} aria-label="Drawing variation seed" /></label>
      <label className="checkbox-control"><input type="checkbox" checked={seedLocked} onChange={e => setSeedLocked(e.target.checked)} />Keep seed when regenerating</label>
    </fieldset>
    <div className="inspector-rule" /><h3>Exported path insights</h3>
    <dl className="path-insights"><div><dt>Actual bounds</dt><dd data-testid="actual-bounds">{draft ? `${draft.preview.bounds.width_mm.toFixed(2)} × ${draft.preview.bounds.height_mm.toFixed(2)} mm` : '—'}</dd></div>
      <div><dt>Drawing distance</dt><dd>{draft ? `${draft.preview.drawing_distance_mm.toFixed(1)} mm` : '—'}</dd></div>
      <div><dt>Travel distance</dt><dd>{draft ? `${draft.preview.travel_distance_mm.toFixed(1)} mm` : '—'}</dd></div>
      <div><dt>Strokes / pen lifts</dt><dd>{draft ? `${draft.preview.strokes} / ${draft.preview.pen_lifts}` : '—'}</dd></div></dl>
    <p className="insight-caption">{draft ? `SHA-256 ${draft.gcode_sha256.slice(0, 12)} · curve tolerance ${draft.chord_tolerance_mm} mm` : 'Metrics and preview come from the final G-code.'}</p>
    <div className="inspector-rule" /><button className="outline-button" disabled={!draft || busy || !available || dirty} onClick={regenerate}><RotateCcw size={15} /> Regenerate drawing</button>
    <div className="download-options"><button disabled={!draft || busy || !available || dirty} onClick={() => download('json')}><ArrowDownToLine size={14} /> Draft JSON</button><button disabled={!draft || busy || !available || dirty} onClick={() => download('svg')}>SVG</button><button disabled={!draft || busy || !available || dirty} onClick={() => download('gcode')}>G-code</button></div>
    <button className="prepare-button" disabled title="Physical preparation requires a measured machine profile and arrives in Phase 4">Prepare for drawing <ArrowRight size={15} /></button>
    <p className="inspector-footnote"><ShieldCheck size={13} /> Downloads are unverified drafts. No hardware motion.</p>
  </div>;
}
