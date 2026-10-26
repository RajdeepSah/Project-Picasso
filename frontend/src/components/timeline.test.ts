import { describe, expect, it } from 'vitest';
import type { DrawingDraft } from '../api/contracts';
import circle from '../testing/circle.json';
import { clock, PEN_SETTLE_SECONDS, position, STEP_SECONDS, timeline, type MotionGeometry } from './timeline';

const fixture = circle as unknown as DrawingDraft;
const reference: MotionGeometry = { label: 'Drawbot reference · 350 mm', separation_mm: 350, anchor_y_mm: 250, spool_diameter_mm: 35, steps_per_turn: 2048 };
const tps = 35 * 3.1416 / 2048;

function line(length: number): DrawingDraft {
  return { ...fixture, preview: { ...fixture.preview, segments: [
    { schema_version: 1, start: [0, 0], end: [0, 0], pen_down: false },
    { schema_version: 1, start: [0, 0], end: [length, 0], pen_down: true },
  ] } } as DrawingDraft;
}

describe('simulation timeline', () => {
  it('times each move by the firmware rope steps it takes', () => {
    // Straight down from between the anchors: both ropes lengthen by the same amount.
    const draft = { ...fixture, preview: { ...fixture.preview, segments: [{ schema_version: 1, start: [0, 0], end: [0, -10], pen_down: false }] } } as DrawingDraft;
    const rope = Math.hypot(175, 260) - Math.hypot(175, 250);
    expect(timeline(draft, reference).seconds).toBeCloseTo(2 * rope / tps * STEP_SECONDS, 6);
  });

  it('counts both ropes shortening then lengthening when a move passes under an anchor', () => {
    const draft = { ...fixture, preview: { ...fixture.preview, segments: [{ schema_version: 1, start: [-200, 0], end: [200, 0], pen_down: false }] } } as DrawingDraft;
    const reach = (x: number, anchor: number) => Math.hypot(x - anchor, 250);
    const rope = 2 * (reach(-200, -175) - 250 + reach(200, -175) - 250);
    expect(timeline(draft, reference).seconds).toBeCloseTo(rope / tps * STEP_SECONDS, 6);
  });

  it('scales with path length and adds a settle for every pen lift and lower', () => {
    const short = timeline(line(10), null), long = timeline(line(100), null);
    expect(short.penChanges).toBe(2);
    const motion = (plan: typeof short) => plan.seconds - plan.penChanges * PEN_SETTLE_SECONDS;
    expect(motion(long) / motion(short)).toBeCloseTo(10, 6);
    // On short strokes the settles dominate, as on the machine.
    expect(short.seconds).toBeLessThan(long.seconds / 4);
    expect(timeline(line(100), reference).seconds).toBeGreaterThan(timeline(line(10), reference).seconds * 4);
  });

  it('estimates the circle fixture at a realistic plotter speed', () => {
    const plan = timeline(fixture, reference);
    expect(plan.distance).toBeCloseTo(fixture.preview.drawing_distance_mm + fixture.preview.travel_distance_mm, 1);
    expect(plan.seconds).toBeGreaterThan(18);
    expect(plan.seconds).toBeLessThan(30);
    expect(timeline(fixture, null).geometry).toBeNull();
  });

  it('holds the pen still while it lowers, then draws', () => {
    const plan = timeline(line(19), null);
    expect(position(plan, 0)).toEqual({ distance: 0, lift: 1 });
    const lowering = position(plan, PEN_SETTLE_SECONDS / 2);
    expect(lowering.distance).toBe(0);
    expect(lowering.lift).toBeCloseTo(.5);
    expect(position(plan, PEN_SETTLE_SECONDS + .5)).toEqual({ distance: 9.5, lift: 0 });
    expect(position(plan, plan.seconds).lift).toBe(1);
  });

  it('formats estimates as a clock', () => {
    expect(clock(0)).toBe('0:00');
    expect(clock(22.2)).toBe('0:23');
    expect(clock(605)).toBe('10:05');
    expect(clock(3725)).toBe('1:02:05');
  });
});
