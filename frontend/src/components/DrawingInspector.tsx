import { useState } from 'react';
import { ChevronDown, Layers, Lock, LockOpen, RefreshCw, SlidersHorizontal, Spline } from 'lucide-react';
import type { DrawingDraft, DrawingSpec, RevisionRequest } from '../api/contracts';
import { paperOptions, type PaperId } from './DrawingPreview';

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

const details: [NonNullable<DrawingSpec['detail']>, string][] = [['sparse', 'Low'], ['standard', 'Medium'], ['dense', 'High']];
const length = (value: number) => value >= 1000 ? `${(value / 1000).toFixed(2)} m` : `${Math.round(value)} mm`;

export function DrawingInspector({ draft, fields, change, busy, available, dirty, aspectLocked, setAspectLocked,
  seedLocked, setSeedLocked, regenerate, paper, setPaper }: {
  draft: DrawingDraft | null; fields: Edits; change: (key: keyof Edits, value: string) => void;
  busy: boolean; available: boolean; dirty: boolean; aspectLocked: boolean; setAspectLocked: (value: boolean) => void;
  seedLocked: boolean; setSeedLocked: (value: boolean) => void; regenerate: () => void;
  paper: PaperId; setPaper: (value: PaperId) => void;
}) {
  const [advanced, setAdvanced] = useState(false);
  const imported = draft?.spec.generator === 'imported';
  const ai = draft?.import_source?.ai;
  const strokes = draft?.preview.strokes ?? 0;
  return <div className="inspector-body drawing-controls">
    <h2 className="inspector-title">Make it yours</h2>
    {!available && <p className="inspector-hint">Reconnect to the local service to adjust drawings.</p>}
    <label className="field-label" htmlFor="paper-select">Paper</label>
    <div className="select-field"><select id="paper-select" value={paper} onChange={event => setPaper(event.target.value as PaperId)} aria-describedby="paper-note">
      {paperOptions.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}</select><ChevronDown size={18} /></div>
    <p id="paper-note" className="sr-only">Frames the preview only. The exported path keeps its own size and coordinates.</p>
    <fieldset disabled={!draft || !available}>
      <legend className="field-label">Size</legend>
      <div className="size-fields">
        <label className="unit-field"><input type="number" min="0.1" max="2000" step="0.1" value={fields.width} onChange={e => change('width', e.target.value)} aria-label="Drawing width in millimetres" /><span aria-hidden="true">mm</span></label>
        <button type="button" className="lock-button" aria-pressed={aspectLocked} aria-label="Lock aspect ratio" title={aspectLocked ? 'Aspect ratio locked' : 'Aspect ratio unlocked'} onClick={() => setAspectLocked(!aspectLocked)}>
          {aspectLocked ? <Lock size={18} /> : <LockOpen size={18} />}</button>
        <label className="unit-field"><input type="number" min="0.1" max="2000" step="0.1" value={fields.height} onChange={e => change('height', e.target.value)} aria-label="Drawing height in millimetres" /><span aria-hidden="true">mm</span></label>
      </div>
      <fieldset className="segmented" disabled={imported}><legend className="field-label">Detail</legend>
        <div className="segmented-options">{details.map(([value, label]) => <label key={value} className={fields.detail === value ? 'checked' : ''}>
          <input type="radio" name="drawing-detail" value={value} checked={fields.detail === value} onChange={() => change('detail', value)} /><span>{label}</span></label>)}</div>
      </fieldset>
    </fieldset>

    <div className="advanced">
      <button type="button" className="advanced-toggle" aria-expanded={advanced} aria-controls="advanced-controls" onClick={() => setAdvanced(!advanced)}>
        <SlidersHorizontal size={19} /> Advanced <ChevronDown className="chevron" size={18} /></button>
      <div id="advanced-controls" className="advanced-body" hidden={!advanced}>
        <fieldset disabled={!draft || !available}><legend className="sr-only">Placement and variation</legend>
          <div className="transform-fields"><label>Rotation °<input type="number" min="-360" max="360" value={fields.rotation} onChange={e => change('rotation', e.target.value)} aria-label="Drawing rotation in degrees" /></label><label>Center X mm<input type="number" min="-2000" max="2000" value={fields.x} onChange={e => change('x', e.target.value)} aria-label="Drawing center X" /></label><label>Center Y mm<input type="number" min="-2000" max="2000" value={fields.y} onChange={e => change('y', e.target.value)} aria-label="Drawing center Y" /></label></div>
          <div className="variation-fields">
            {draft?.spec.generator === 'mandala' && <label>Petals<input type="number" min="3" max="64" value={fields.petals} onChange={e => change('petals', e.target.value)} aria-label="Mandala petals" /></label>}
            {draft?.spec.generator === 'spiral' && <label>Turns<input type="number" min="0.1" max="100" step="0.1" value={fields.turns} onChange={e => change('turns', e.target.value)} aria-label="Spiral turns" /></label>}
            {draft?.spec.generator === 'pattern' && <label>Symmetry<input type="number" min="2" max="64" value={fields.symmetry} onChange={e => change('symmetry', e.target.value)} aria-label="Pattern symmetry" /></label>}
            <label>Variation seed<input disabled={imported} type="number" min="0" max="4294967295" value={fields.seed} onChange={e => change('seed', e.target.value)} aria-label="Drawing variation seed" /></label>
          </div>
          <label className="checkbox-control"><input disabled={imported} type="checkbox" checked={seedLocked} onChange={e => setSeedLocked(e.target.checked)} />Keep seed when regenerating</label>
        </fieldset>
        <dl className="path-insights"><div><dt>Actual bounds</dt><dd data-testid="actual-bounds">{draft ? `${draft.preview.bounds.width_mm.toFixed(2)} × ${draft.preview.bounds.height_mm.toFixed(2)} mm` : '—'}</dd></div>
          <div><dt>Drawing distance</dt><dd>{draft ? `${draft.preview.drawing_distance_mm.toFixed(1)} mm` : '—'}</dd></div>
          <div><dt>Travel distance</dt><dd>{draft ? `${draft.preview.travel_distance_mm.toFixed(1)} mm` : '—'}</dd></div>
          <div><dt>Strokes / pen lifts</dt><dd>{draft ? `${draft.preview.strokes} / ${draft.preview.pen_lifts}` : '—'}</dd></div></dl>
        <p className="insight-caption">{draft ? `Revision ${draft.revision} · SHA-256 ${draft.gcode_sha256.slice(0, 12)} · curve tolerance ${draft.chord_tolerance_mm} mm` : 'Metrics and preview come from the final G-code.'}</p>
        {draft?.import_source && <details className="import-provenance"><summary>{ai ? `AI source: OpenAI ${ai.model}` : `Imported source: ${draft.import_source.filename}`}</summary><p>Original bounds: {draft.import_source.original_bounds.width_mm.toFixed(2)} × {draft.import_source.original_bounds.height_mm.toFixed(2)} mm.</p>{draft.import_source.notes.map(note => <p key={note}>{note}</p>)}</details>}
      </div>
    </div>

    <dl className="drawing-stats">
      <div><dt><Layers size={22} strokeWidth={1.6} /><span className="sr-only">Paths</span></dt><dd>{draft ? `${strokes} ${strokes === 1 ? 'path' : 'paths'}` : 'No paths yet'}</dd></div>
      <div><dt><Spline size={22} strokeWidth={1.6} /><span className="sr-only">Line length</span></dt><dd>{draft ? `${length(draft.preview.drawing_distance_mm)} of line` : 'Line length appears here'}</dd></div>
    </dl>
    <button className="regenerate-button" disabled={!draft || busy || !available || dirty || imported} onClick={regenerate}
      title={ai ? 'Submit the command again for a new AI image' : imported ? 'Imported drawings keep their original paths' : seedLocked ? 'Rebuild with the same seed' : 'Try a new variation'}><RefreshCw size={20} />Regenerate<span className="sr-only"> drawing</span></button>
  </div>;
}
