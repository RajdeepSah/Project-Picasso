import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react';
import { Grid2X2, Hand, Minus, MousePointer2, Pause, PenLine, Play, Plus, Route, Scan, Square, Timer, TriangleAlert, Usb } from 'lucide-react';
import type { DrawingDraft } from '../api/contracts';
import { clock, isSpeed, position, simulationSpeeds, timeline, type MotionGeometry, type SimulationSpeed } from './timeline';

/** A run streaming on the machine, shown over the preview. Position is commanded, not measured. */
export type Execution = { fraction: number | null; position: [number, number] | null; percent: number; stop: () => void; stopping: boolean };

const sheets = { A5: [148, 210], A4: [210, 297], A3: [297, 420], Letter: [215.9, 279.4] } as const;
type Sheet = keyof typeof sheets;
/** A page drawn around the preview, centred on the drawing origin. It frames the view only; exported paths are unchanged. */
export type PaperId = 'fit' | `${Sheet}-${'portrait' | 'landscape'}`;
export const paperOptions: { id: PaperId; label: string }[] = [
  ...(Object.keys(sheets) as Sheet[]).flatMap(name => (['portrait', 'landscape'] as const).map(side => ({ id: `${name}-${side}` as PaperId, label: `${name} · ${side === 'portrait' ? 'Portrait' : 'Landscape'}` }))),
  { id: 'fit', label: 'Fit to drawing' },
];
export const isPaper = (value: unknown): value is PaperId => paperOptions.some(option => option.id === value);
export function paperSize(id: PaperId): [number, number] | null {
  if (id === 'fit') return null;
  const [name, side] = id.split('-') as [Sheet, string];
  const [width, height] = sheets[name];
  return side === 'portrait' ? [width, height] : [height, width];
}
export const paperLabel = (id: PaperId) => paperOptions.find(option => option.id === id)?.label ?? 'Fit to drawing';

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

/** Pen-down and travel path data for the first `distance` millimetres of the path. */
function trace(draft: DrawingDraft, distance: number) {
  let remaining = distance;
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

const mm = (value: number) => Number(value.toFixed(1)).toString();

function storedSpeed(): SimulationSpeed {
  try { const value = Number(window.localStorage.getItem('picasso.simulationSpeed')); return isSpeed(value) ? value : 1; } catch { return 1; }
}

export function DrawingPreview({ draft, busy, paper, grid, setGrid, zoom, setZoom, execute, executeBlocked, execution, geometry }: {
  draft: DrawingDraft | null; busy: boolean; paper: PaperId; grid: boolean; setGrid: (value: boolean) => void;
  zoom: number; setZoom: (value: number) => void;
  execute: () => void; executeBlocked: string; execution: Execution | null;
  /** Rope geometry for the playback time estimate; null falls back to a nominal speed. */
  geometry: MotionGeometry | null;
}) {
  const [showTravel, setShowTravel] = useState(true);
  /** Share of the estimated machine time played back. */
  const [progress, setProgress] = useState(1);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeedState] = useState<SimulationSpeed>(storedSpeed);
  const setSpeed = (value: SimulationSpeed) => { setSpeedState(value); try { window.localStorage.setItem('picasso.simulationSpeed', String(value)); } catch { /* preference only */ } };
  const [tool, setTool] = useState<'select' | 'pan'>('select');
  const [pan, setPan] = useState<[number, number]>([0, 0]);
  const drag = useRef<{ x: number; y: number; from: [number, number] } | null>(null);
  useEffect(() => { setProgress(1); setPlaying(false); }, [draft?.revision_id]);
  useEffect(() => { setPan([0, 0]); }, [draft?.drawing_id]);
  const executing = !!execution;
  useEffect(() => { if (executing) setPlaying(false); }, [executing]);
  const plan = useMemo(() => draft ? timeline(draft, geometry) : null, [draft, geometry]);
  // Playback runs on estimated machine time scaled by the chosen speed; the machine itself is never told.
  useEffect(() => {
    if (!playing || !plan) return;
    if (plan.seconds <= 0) { setProgress(1); return; }
    let frame = 0, last = performance.now();
    const tick = (now: number) => {
      // Frames stop in a hidden tab; resume from there instead of jumping ahead.
      const elapsed = Math.min(.1, Math.max(0, now - last) / 1000);
      last = now;
      setProgress(value => Math.min(1, value + elapsed * speed / plan.seconds));
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [playing, speed, plan]);
  useEffect(() => { if (progress >= 1) setPlaying(false); }, [progress]);
  const shown = execution?.fraction ?? progress;
  const pen = plan && progress < 1 ? position(plan, progress * plan.seconds) : { distance: Infinity, lift: 1 };
  const total = draft ? draft.preview.drawing_distance_mm + draft.preview.travel_distance_mm : 0;
  const distance = execution?.fraction != null ? execution.fraction * total : pen.distance;
  const left = plan ? plan.seconds * (progress < 1 ? 1 - progress : 1) / speed : 0;
  const estimate = plan && `Estimated machine time ${clock(plan.seconds)}: ${(plan.distance / 1000).toFixed(2)} m of path and ${plan.penChanges} pen ${plan.penChanges === 1 ? 'move' : 'moves'} at firmware step timing`
    + `${plan.geometry ? ` with ${plan.geometry} geometry` : ' at a nominal speed'}. At ${speed}× the preview takes ${clock(plan.seconds / speed)}. Simulation only; the machine's speed is unchanged.`;
  const sheet = paperSize(paper);
  const [sheetWidth, sheetHeight] = sheet ?? [0, 0];
  const paths = useMemo(() => {
    if (!draft) return null;
    const box = draft.preview.bounds;
    let left = Math.min(box.min_x_mm, 0), right = Math.max(box.max_x_mm, 0);
    let bottom = Math.min(box.min_y_mm, 0), top = Math.max(box.max_y_mm, 0);
    if (sheetWidth) { left = -sheetWidth / 2; right = sheetWidth / 2; bottom = -sheetHeight / 2; top = sheetHeight / 2; }
    else {
      const margin = Math.max(5, Math.max(right - left, top - bottom) * .09);
      left -= margin; right += margin; bottom -= margin; top += margin;
    }
    const overflow = !!sheetWidth && (box.min_x_mm < left - .01 || box.max_x_mm > right + .01 || box.min_y_mm < bottom - .01 || box.max_y_mm > top + .01);
    return { viewBox: `${left} ${-top} ${right - left} ${top - bottom}`, ratio: (right - left) / (top - bottom), overflow, ...trace(draft, distance), left, right, bottom, top };
  }, [draft, distance, sheetWidth, sheetHeight]);
  const overlay = execution?.fraction != null;
  // While the machine draws, the whole path stays visible faintly beneath the acknowledged part.
  const pending = useMemo(() => draft && overlay ? trace(draft, Infinity).drawing : '', [draft, overlay]);
  const machineCursor = overlay ? execution!.position : null;
  const ratio = paths?.ratio ?? (sheet ? sheet[0] / sheet[1] : 210 / 297);
  const fit = () => { setZoom(100); setPan([0, 0]); };
  const sheetName = paper.split('-')[0];

  const grab = (event: PointerEvent<HTMLDivElement>) => {
    if (tool !== 'pan' || event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, from: pan };
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    setPan([drag.current.from[0] + event.clientX - drag.current.x, drag.current.from[1] + event.clientY - drag.current.y]);
  };
  const release = () => { drag.current = null; };
  const nudge = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 60 : 20;
    const delta = ({ ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] } as Record<string, [number, number]>)[event.key];
    if (tool !== 'pan' || !delta) return;
    event.preventDefault(); setPan(([x, y]) => [x + delta[0], y + delta[1]]);
  };

  const caption = draft ? `${draft.preview.bounds.width_mm.toFixed(2)} × ${draft.preview.bounds.height_mm.toFixed(2)} mm drawing`
    + (sheet ? ` · ${sheetName} ${mm(sheet[0])} × ${mm(sheet[1])} mm page, centred on (0, 0)` : ' · fit to path')
    : sheet ? `Blank ${sheetName} page · ${mm(sheet[0])} × ${mm(sheet[1])} mm` : 'Blank page · fits your drawing';

  return <section className="preview" aria-label="Drawing preview">
    <div className={`stage ${grid ? 'show-grid' : ''} tool-${tool}`} aria-busy={busy} onPointerDown={grab} onPointerMove={move} onPointerUp={release} onPointerCancel={release}
      onKeyDown={nudge} tabIndex={tool === 'pan' ? 0 : undefined} role={tool === 'pan' ? 'group' : undefined} aria-label={tool === 'pan' ? 'Canvas. Drag or use the arrow keys to pan.' : undefined}>
      <div className="paper-frame" style={{ '--paper-ratio': ratio, transform: `translate(${pan[0]}px, ${pan[1]}px) scale(${zoom / 100})` } as CSSProperties}>
        <div className={`paper ${draft ? 'has-drawing' : ''}`}>
          {draft && paths ? <svg role="img" aria-label={`${draft.title} drawing path preview, simulation only`} viewBox={paths.viewBox} data-gcode-sha256={draft.gcode_sha256}>
            <title>{draft.title} · exported path · machine position unmeasured</title>
            <g className="preview-axes"><path d={`M${paths.left},0H${paths.right}M0,${-paths.top}V${-paths.bottom}`} /></g>
            {pending && <path className="pending-path" d={pending} />}
            {showTravel && <path data-testid="travel-path" className="travel-path" d={paths.travel} />}
            <path data-testid="drawing-path" className="drawing-path" d={paths.drawing} />
            <circle className="simulation-origin" cx="0" cy="0" r="1" vectorEffect="non-scaling-stroke" />
            {!execution && (playing || progress < 1) && <g data-testid="playback-cursor" className={`playback-cursor ${pen.lift > .5 ? 'pen-up' : 'pen-down'}`} transform={`translate(${paths.cursor[0]} ${-paths.cursor[1]})`}>
              <circle className="pen-halo" r={1.2 + pen.lift * 1.6} opacity={pen.lift * .45} />
              <circle className="pen-tip" r="1.2" />
            </g>}
            {machineCursor && <circle data-testid="machine-cursor" className="machine-cursor" cx={machineCursor[0]} cy={-machineCursor[1]} r="1.4"><title>Commanded machine position (not measured)</title></circle>}
          </svg> : <div className="paper-empty">
            <div className="pen-emblem"><PenLine size={26} strokeWidth={1.4} /></div>
            <h3>The page is yours.</h3><p>Start with a simple idea.<br />Your drawing will appear here.</p>
          </div>}
          {busy && <div className="paper-busy"><span className="spinner" />{draft ? 'Updating the path…' : 'Drawing your idea…'}</div>}
        </div>
        <p className="paper-caption">{caption}</p>
      </div>
      {paths?.overflow && <p className="stage-warning"><TriangleAlert size={15} />The drawing extends past the {sheetName} page. The exported path is unchanged.</p>}
    </div>

    <div className="tool-rail" role="toolbar" aria-label="Canvas tools" aria-orientation="vertical">
      <button className={tool === 'select' ? 'active' : ''} aria-pressed={tool === 'select'} aria-label="Select tool" data-tip="Select" onClick={() => setTool('select')}><MousePointer2 size={20} /></button>
      <button className={tool === 'pan' ? 'active' : ''} aria-pressed={tool === 'pan'} aria-label="Pan tool" data-tip="Pan · drag the page" onClick={() => setTool('pan')}><Hand size={20} /></button>
      <button className={showTravel ? 'on' : ''} aria-pressed={showTravel} aria-label="Toggle travel paths" data-tip="Pen-up travel paths" onClick={() => setShowTravel(!showTravel)}><Route size={20} /></button>
      <button className={grid ? 'on' : ''} aria-pressed={grid} aria-label="Toggle preview grid" data-tip="Dot grid" onClick={() => setGrid(!grid)}><Grid2X2 size={20} /></button>
      <button aria-label="Reset preview zoom" data-tip="Fit to view" onClick={fit}><Scan size={20} /></button>
    </div>

    <div className="playback-bar">
      <button className="play-button" disabled={!draft || busy || !!execution} onClick={() => { if (progress >= 1) setProgress(0); setPlaying(!playing); }} aria-label={playing ? 'Pause simulation' : 'Play simulation'}>
        {playing ? <Pause size={15} /> : <Play size={15} />}<span>Simulation</span></button>
      {draft && <><input aria-label="Simulation progress" type="range" min="0" max="100" disabled={!!execution} value={Math.round(shown * 100)} onChange={event => { setPlaying(false); setProgress(Number(event.target.value) / 100); }}
        title={execution ? 'Commands acknowledged by the machine · commanded position, not measured' : 'Simulated playback at estimated machine timing'} />
        <span className="playback-value">{execution ? `${execution.percent}% acked` : `${Math.round(progress * 100)}%`}</span>
        {!execution && plan && <>
          <span className="playback-eta" title={estimate ?? undefined}><Timer size={13} /><span>{clock(left)}<span className="eta-word">{progress < 1 ? ' left' : ''}</span></span></span>
          <select className="speed-select" aria-label="Simulation speed" value={speed} title="Preview playback speed only. The machine always draws at its firmware speed."
            onChange={event => { const value = Number(event.target.value); if (isSpeed(value)) setSpeed(value); }}>
            {simulationSpeeds.map(value => <option key={value} value={value}>{value}×</option>)}
          </select></>}</>}
      <span className="bar-divider" />
      <button className="execute-button" disabled={!execution && !!executeBlocked} title={execution ? 'Show the run on the machine' : executeBlocked || 'Draw this on the machine over USB'} onClick={execute}><Usb size={15} />{execution ? `Executing · ${execution.percent}%` : 'Execute'}</button>
      {execution && <button className="execute-stop" disabled={execution.stopping} onClick={execution.stop} aria-label="Stop the machine"><Square size={12} />Stop</button>}
    </div>

    <div className="zoom-controls" role="group" aria-label="Zoom">
      <button aria-label="Zoom out" disabled={zoom <= 50} onClick={() => setZoom(Math.max(50, zoom - 25))}><Minus size={17} /></button>
      <output aria-label="Preview zoom">{zoom}%</output>
      <button aria-label="Zoom in" disabled={zoom >= 200} onClick={() => setZoom(Math.min(200, zoom + 25))}><Plus size={17} /></button>
    </div>
  </section>;
}
