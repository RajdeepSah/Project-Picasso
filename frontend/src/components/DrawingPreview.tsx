import { useEffect, useMemo, useState } from 'react';
import { Grid2X2, Maximize2, Minus, Pause, PenLine, Play, Plus, Route, ShieldCheck, Square, Usb } from 'lucide-react';
import type { DrawingDraft } from '../api/contracts';

/** A run streaming on the machine, shown over the preview. Position is commanded, not measured. */
export type Execution = { fraction: number | null; position: [number, number] | null; percent: number; stop: () => void; stopping: boolean };

/** Share of the path (drawing + travel) covered by the first `acknowledged` G-code lines, in streaming order. */
export function executedFraction(draft: DrawingDraft, acknowledged: number) {
  const total = draft.preview.drawing_distance_mm + draft.preview.travel_distance_mm;
  if (total <= 0) return 0;
  let [x, y] = draft.preview.expected_start_mm ?? [0, 0];
  let done = 0;
  for (const line of draft.gcode.split('\n').slice(0, acknowledged)) {
    const match = /^G[01] X(-?[\d.]+) Y(-?[\d.]+)/.exec(line);
    if (!match) continue;
    const next: [number, number] = [Number(match[1]), Number(match[2])];
    done += Math.hypot(next[0] - x, next[1] - y);
    [x, y] = next;
  }
  return Math.min(1, done / total);
}

/** Pen-down and travel path data for the first `fraction` of the path distance. */
function trace(draft: DrawingDraft, fraction: number) {
  let remaining = (draft.preview.drawing_distance_mm + draft.preview.travel_distance_mm) * fraction;
  const drawing: string[] = [], travel: string[] = [];
  let cursor = draft.preview.expected_start_mm ?? [0, 0];
  for (const segment of draft.preview.segments) {
    const length = Math.hypot(segment.end[0] - segment.start[0], segment.end[1] - segment.start[1]);
    if (remaining <= 0) break;
    const ratio = length === 0 ? 1 : Math.min(1, remaining / length);
    const end: [number, number] = [segment.start[0] + (segment.end[0] - segment.start[0]) * ratio,
      segment.start[1] + (segment.end[1] - segment.start[1]) * ratio];
    (segment.pen_down ? drawing : travel).push(`M${segment.start[0]},${-segment.start[1]}L${end[0]},${-end[1]}`);
    cursor = end;
    remaining -= length;
  }
  return { drawing: drawing.join(' '), travel: travel.join(' '), cursor };
}

export function DrawingPreview({ draft, busy, grid, setGrid, zoom, setZoom, execute, executeBlocked, execution }: {
  draft: DrawingDraft | null; busy: boolean; grid: boolean; setGrid: (value: boolean) => void;
  zoom: number; setZoom: (value: number) => void;
  execute: () => void; executeBlocked: string; execution: Execution | null;
}) {
  const [showTravel, setShowTravel] = useState(true);
  const [progress, setProgress] = useState(1);
  const [playing, setPlaying] = useState(false);
  useEffect(() => { setProgress(1); setPlaying(false); }, [draft?.revision_id]);
  const executing = !!execution;
  useEffect(() => { if (executing) setPlaying(false); }, [executing]);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setProgress(value => Math.min(1, value + .0125)), 50);
    return () => window.clearInterval(timer);
  }, [playing]);
  useEffect(() => { if (progress >= 1) setPlaying(false); }, [progress]);
  const shown = execution?.fraction ?? progress;
  const paths = useMemo(() => {
    if (!draft) return null;
    const box = draft.preview.bounds;
    const left = Math.min(box.min_x_mm, 0), right = Math.max(box.max_x_mm, 0);
    const bottom = Math.min(box.min_y_mm, 0), top = Math.max(box.max_y_mm, 0);
    const margin = Math.max(5, Math.max(right - left, top - bottom) * .09);
    const viewBox = `${left - margin} ${-top - margin} ${right - left + margin * 2} ${top - bottom + margin * 2}`;
    return { viewBox, ...trace(draft, shown), left: left - margin, right: right + margin, bottom: bottom - margin, top: top + margin };
  }, [draft, shown]);
  const overlay = execution?.fraction != null;
  // While the machine draws, the whole path stays visible faintly beneath the acknowledged part.
  const pending = useMemo(() => draft && overlay ? trace(draft, 1).drawing : '', [draft, overlay]);
  const machineCursor = overlay ? execution!.position : null;
  return <section className="preview-panel panel" aria-label="Drawing preview">
    <div className="panel-toolbar"><div className="panel-title"><span className={`status-dot ${draft ? 'online' : ''}`} /><h2>Drawing preview</h2><span className="small-tag">{busy ? 'UPDATING' : execution ? 'EXECUTING' : draft ? 'SIMULATION' : 'EMPTY CANVAS'}</span></div><div className="preview-actions">
      <button className={`icon-button ${showTravel ? 'selected' : ''}`} aria-label="Toggle travel paths" aria-pressed={showTravel} onClick={() => setShowTravel(!showTravel)} title="Pen-up travel paths"><Route size={17} /></button>
      <button className={`icon-button ${grid ? 'selected' : ''}`} aria-label="Toggle preview grid" aria-pressed={grid} onClick={() => setGrid(!grid)}><Grid2X2 size={17} /></button>
      <button className="icon-button" aria-label="Reset preview zoom" title="Fit drawing" onClick={() => setZoom(100)}><Maximize2 size={17} /></button>
    </div></div>
    <div className={`preview-stage ${grid ? 'show-grid' : ''}`} aria-busy={busy}>
      <div className="canvas-meta"><span><span className="tiny-dot" />{draft ? `${draft.title.toUpperCase()} · REVISION ${draft.revision}` : 'PREVIEW WORKSPACE'}</span><span>mm</span></div>
      <div className={`paper ${draft ? 'has-drawing' : ''}`} style={{ transform: `scale(${zoom / 100})` }}>
        <span className="paper-corner top-left" /><span className="paper-corner bottom-right" />
        {draft && paths ? <svg role="img" aria-label={`${draft.title} drawing path preview, simulation only`} viewBox={paths.viewBox} data-gcode-sha256={draft.gcode_sha256}>
          <title>{draft.title} · exported path · machine position unmeasured</title>
          <g className="preview-axes"><path d={`M${paths.left},0H${paths.right}M0,${-paths.top}V${-paths.bottom}`} /></g>
          {pending && <path className="pending-path" d={pending} />}
          {showTravel && <path data-testid="travel-path" className="travel-path" d={paths.travel} />}
          <path data-testid="drawing-path" className="drawing-path" d={paths.drawing} />
          <circle className="simulation-origin" cx="0" cy="0" r="1" vectorEffect="non-scaling-stroke" />
          {playing && !execution && <circle className="playback-cursor" cx={paths.cursor[0]} cy={-paths.cursor[1]} r="1.2" />}
          {machineCursor && <circle data-testid="machine-cursor" className="machine-cursor" cx={machineCursor[0]} cy={-machineCursor[1]} r="1.4"><title>Commanded machine position (not measured)</title></circle>}
        </svg> : <div className="paper-empty"><div className="pen-emblem"><PenLine size={30} strokeWidth={1.25} /></div><h3>The page is yours.</h3><p>Start with a simple idea.<br />Your drawing will appear here.</p><span className="canvas-phase"><span /> OFFLINE DRAWING ENGINE READY</span></div>}
      </div>
      <div className="canvas-footer"><span>{draft ? `${draft.preview.bounds.width_mm.toFixed(2)} × ${draft.preview.bounds.height_mm.toFixed(2)} mm · fit to path` : 'Blank A4 page · 210 × 297 mm'}</span><div className="zoom-controls"><button aria-label="Zoom out" disabled={zoom <= 75} onClick={() => setZoom(Math.max(75, zoom - 25))}><Minus size={14} /></button><output aria-label="Preview zoom">{zoom}%</output><button aria-label="Zoom in" disabled={zoom >= 150} onClick={() => setZoom(Math.min(150, zoom + 25))}><Plus size={14} /></button></div></div>
    </div>
    <div className="preview-bottom"><span><ShieldCheck size={14} /> Draft preview · assumed start (0, 0)</span><div className="preview-run-actions">
      <button className="playback-button" disabled={!draft || busy || !!execution} onClick={() => { if (progress >= 1) setProgress(0); setPlaying(!playing); }} aria-label={playing ? 'Pause simulation' : 'Play simulation'}>{playing ? <Pause size={14} /> : <Play size={14} />} Simulation</button>
      <button className="execute-button" disabled={!execution && !!executeBlocked} title={execution ? 'Show the run on the machine' : executeBlocked || 'Draw this on the machine over USB'} onClick={execute}><Usb size={13} />{execution ? `Executing · ${execution.percent}%` : 'Execute'}</button>
      {execution && <button className="execute-stop" disabled={execution.stopping} onClick={execution.stop} aria-label="Stop the machine"><Square size={12} />Stop</button>}
    </div></div>
    {draft && <div className="playback-controls"><input aria-label="Simulation progress" type="range" min="0" max="100" disabled={!!execution} value={Math.round(shown * 100)} onChange={event => { setPlaying(false); setProgress(Number(event.target.value) / 100); }} /><span>{execution ? `${execution.percent}% of commands acknowledged by the machine · commanded position, not measured` : `${Math.round(progress * 100)}% · visual playback, not machine timing`}</span></div>}
  </section>;
}
