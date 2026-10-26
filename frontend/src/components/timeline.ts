import type { DrawingDraft, MachineProfile } from '../api/contracts';

/** Rope geometry an estimate is computed from: a measured profile or a source reference. */
export type MotionGeometry = Pick<MachineProfile, 'label' | 'separation_mm' | 'anchor_y_mm' | 'spool_diameter_mm' | 'steps_per_turn'>;

// Canonical firmware timing (firmware/WallDrawingMachine/picasso_config.h). Every motor step is
// its own TinyStepper move ramping from rest, about 2236 us, and moveto() steps the two motors
// one after the other, so a move takes (left steps + right steps) x 2236 us at constant speed.
export const STEP_SECONDS = 0.002236;
// PICASSO_PEN_DOWN_SETTLE_MS and PICASSO_PEN_UP_SETTLE_MS: the pen holds still while the servo settles.
export const PEN_SETTLE_SECONDS = 0.3;
// Only used without any profile: the 350 mm source reference averages about 19 mm/s near the origin.
const NOMINAL_MM_PER_SECOND = 19;

/** Playback multipliers. They change the preview only; nothing here reaches the machine. */
export const simulationSpeeds = [0.5, 1, 2, 5, 10, 20] as const;
export type SimulationSpeed = typeof simulationSpeeds[number];
export const isSpeed = (value: unknown): value is SimulationSpeed => simulationSpeeds.includes(value as SimulationSpeed);

type Phase = { kind: 'draw' | 'travel' | 'lower' | 'lift'; at: number; seconds: number; from: number; length: number };
/** Estimated machine time for each move and pen change, in streaming order. */
export type Timeline = { phases: Phase[]; seconds: number; distance: number; penChanges: number; geometry: string | null };

/** Rope length change along a straight move: distance to the anchor is convex along a line, so it falls to the closest point and rises after. */
function ropeTravel(start: [number, number], end: [number, number], anchor: [number, number]) {
  const dx = end[0] - start[0], dy = end[1] - start[1], squared = dx * dx + dy * dy;
  const t = squared === 0 ? 0 : Math.max(0, Math.min(1, ((anchor[0] - start[0]) * dx + (anchor[1] - start[1]) * dy) / squared));
  const reach = (x: number, y: number) => Math.hypot(x - anchor[0], y - anchor[1]);
  const closest = reach(start[0] + dx * t, start[1] + dy * t);
  return reach(...start) - closest + reach(...end) - closest;
}

function moveSeconds(start: [number, number], end: [number, number], length: number, geometry: MotionGeometry | null) {
  if (!geometry) return length / NOMINAL_MM_PER_SECOND;
  // Legacy TPS: rope millimetres per step, with the firmware's 3.1416.
  const tps = geometry.spool_diameter_mm * 3.1416 / geometry.steps_per_turn;
  const half = geometry.separation_mm / 2;
  const rope = ropeTravel(start, end, [-half, geometry.anchor_y_mm]) + ropeTravel(start, end, [half, geometry.anchor_y_mm]);
  return rope / tps * STEP_SECONDS;
}

export function timeline(draft: DrawingDraft, geometry: MotionGeometry | null): Timeline {
  const phases: Phase[] = [];
  let at = 0, distance = 0, penDown = false, penChanges = 0;
  const push = (kind: Phase['kind'], seconds: number, length = 0) => {
    phases.push({ kind, at, seconds, from: distance, length });
    at += seconds; distance += length;
  };
  for (const segment of draft.preview.segments) {
    if (segment.pen_down !== penDown) { penDown = segment.pen_down; penChanges++; push(penDown ? 'lower' : 'lift', PEN_SETTLE_SECONDS); }
    const length = Math.hypot(segment.end[0] - segment.start[0], segment.end[1] - segment.start[1]);
    push(penDown ? 'draw' : 'travel', moveSeconds(segment.start, segment.end, length, geometry), length);
  }
  // Exports end with the pen raised.
  if (penDown) { penChanges++; push('lift', PEN_SETTLE_SECONDS); }
  return { phases, seconds: at, distance, penChanges, geometry: geometry?.label ?? null };
}

const ease = (value: number) => value * value * (3 - 2 * value);

/** Path distance covered and pen height (0 on the paper, 1 raised) at `time` seconds of machine time. */
export function position(plan: Timeline, time: number) {
  const { phases } = plan;
  if (!phases.length || time <= 0) return { distance: 0, lift: 1 };
  let low = 0, high = phases.length - 1;
  while (low < high) {
    const middle = (low + high + 1) >> 1;
    if (phases[middle].at <= time) low = middle; else high = middle - 1;
  }
  const phase = phases[low];
  const done = phase.seconds > 0 ? Math.min(1, (time - phase.at) / phase.seconds) : 1;
  const lift = phase.kind === 'draw' ? 0 : phase.kind === 'travel' ? 1 : phase.kind === 'lift' ? ease(done) : 1 - ease(done);
  return { distance: phase.from + phase.length * done, lift };
}

/** m:ss, or h:mm:ss from an hour. */
export function clock(seconds: number) {
  const whole = Math.ceil(Math.max(0, seconds));
  const hours = Math.floor(whole / 3600), minutes = Math.floor(whole / 60) % 60, rest = String(whole % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}
