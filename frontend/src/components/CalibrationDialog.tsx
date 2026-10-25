import { useEffect, useRef, useState } from 'react';
import { Ruler, X } from 'lucide-react';
import type { CalibrationInput, CalibrationProfile, ProfilesResponse } from '../api/contracts';
import { saveCalibration } from '../api/client';

type Values = Record<string, string>;
const numbers = [
  ['separation_mm', 'Motor spacing mm'], ['anchor_y_mm', 'Anchor Y above origin mm'],
  ['spool_diameter_mm', 'Spool diameter mm'], ['steps_per_turn', 'Steps per turn'],
  ['pen_up_degrees', 'Pen up degrees'], ['pen_down_degrees', 'Pen down degrees'],
  ['min_x_mm', 'Allowed minimum X mm'], ['max_x_mm', 'Allowed maximum X mm'],
  ['min_y_mm', 'Allowed minimum Y mm'], ['max_y_mm', 'Allowed maximum Y mm'],
  ['margin_mm', 'Boundary margin mm'], ['rope_min_mm', 'Minimum rope length mm'], ['rope_max_mm', 'Maximum rope length mm'],
] as const;
function valuesFrom(profile?: CalibrationProfile): Values {
  return profile ? { ...Object.fromEntries(numbers.map(([key]) => [key, String(key in profile.allowed_region ? profile.allowed_region[key as keyof typeof profile.allowed_region] : profile[key as keyof CalibrationProfile])])),
    label: profile.label, board: profile.board, measured_by: profile.measured_by, measurement_notes: profile.measurement_notes, origin_procedure: profile.origin_procedure,
    base_reference_id: profile.base_reference_id,
  } : { label: '', board: '', measured_by: '', measurement_notes: '', origin_procedure: '', base_reference_id: 'reference-350',
    separation_mm: '350', anchor_y_mm: '250', spool_diameter_mm: '35', steps_per_turn: '2048', pen_up_degrees: '85', pen_down_degrees: '70',
    min_x_mm: '', max_x_mm: '', min_y_mm: '', max_y_mm: '', margin_mm: '5', rope_min_mm: '', rope_max_mm: '' };
}

export function CalibrationDialog({ profiles, close, saved }: { profiles: ProfilesResponse; close: () => void; saved: () => void }) {
  const initial = profiles.measured_profiles?.find(profile => profile.id === profiles.active_profile_id);
  const [editing, setEditing] = useState<CalibrationProfile | undefined>(initial);
  const [values, setValues] = useState<Values>(() => valuesFrom(initial));
  const [checks, setChecks] = useState({ firmware_matches_measurements: initial?.firmware_matches_measurements ?? false,
    pen_lift_and_holding_tested: initial?.pen_lift_and_holding_tested ?? false, workspace_tested: initial?.workspace_tested ?? false, verified: initial?.verified ?? false });
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  const change = (key: string, value: string) => setValues(current => ({ ...current, [key]: value }));
  const submit = async () => {
    if (Object.values(values).some(value => !value.trim())) { setError('Fill the measured values, board, observer, notes and origin procedure. Source values alone are not physical verification.'); return; }
    if (numbers.some(([key]) => !Number.isFinite(Number(values[key])))) { setError('Every measurement must be a finite number.'); return; }
    setBusy(true); setError('');
    try {
      const numeric = Object.fromEntries(numbers.map(([key]) => [key, Number(values[key])]));
      const calibration: CalibrationInput = { label: values.label, board: values.board, measured_by: values.measured_by,
        measurement_notes: values.measurement_notes, origin_procedure: values.origin_procedure,
        base_reference_id: values.base_reference_id as CalibrationInput['base_reference_id'],
        separation_mm: numeric.separation_mm, anchor_y_mm: numeric.anchor_y_mm, spool_diameter_mm: numeric.spool_diameter_mm,
        steps_per_turn: numeric.steps_per_turn, pen_up_degrees: numeric.pen_up_degrees, pen_down_degrees: numeric.pen_down_degrees,
        rope_min_mm: numeric.rope_min_mm, rope_max_mm: numeric.rope_max_mm,
        allowed_region: { min_x_mm: numeric.min_x_mm, max_x_mm: numeric.max_x_mm, min_y_mm: numeric.min_y_mm, max_y_mm: numeric.max_y_mm, margin_mm: numeric.margin_mm }, ...checks };
      await saveCalibration({ calibration, expected_revision: editing?.revision, select_for_preparation: true }, editing?.id);
      saved();
    } catch (error) { setError(error instanceof Error ? error.message : 'Profile could not be saved.'); }
    finally { setBusy(false); }
  };
  return <dialog ref={ref} onCancel={close} className="studio-dialog wide-dialog" aria-labelledby="calibration-title"><div className="dialog-top"><span className="eyebrow">MACHINE MEASUREMENTS</span><button className="icon-button" onClick={close} aria-label="Close calibration"><X size={18} /></button></div><h2 id="calibration-title">Record a machine profile</h2><p>These are your recorded measurements and checks. The app does not observe the wiring or flashed firmware. No configuration is sent to the Arduino.</p>
    <label className="form-field">Measured profile<select value={editing?.id ?? ''} aria-label="Edit measured profile" onChange={event => { const profile = profiles.measured_profiles?.find(item => item.id === event.target.value); setEditing(profile); setValues(valuesFrom(profile)); setChecks({ firmware_matches_measurements: profile?.firmware_matches_measurements ?? false, pen_lift_and_holding_tested: profile?.pen_lift_and_holding_tested ?? false, workspace_tested: profile?.workspace_tested ?? false, verified: profile?.verified ?? false }); }}><option value="">New measured profile</option>{profiles.measured_profiles?.map(profile => <option key={profile.id} value={profile.id}>{profile.label} · v{profile.version}</option>)}</select></label>
    <label className="form-field">Profile name<input value={values.label} onChange={event => change('label', event.target.value)} aria-label="Profile name" /></label>
    <div className="form-grid"><label className="form-field">Source firmware reference<select value={values.base_reference_id} onChange={event => { change('base_reference_id', event.target.value); change('separation_mm', event.target.value === 'reference-350' ? '350' : '400'); }}><option value="reference-350">Drawbot copy · 350 mm</option><option value="reference-400">SD copy · 400 mm</option></select></label><label className="form-field">Actual board model<input value={values.board} onChange={event => change('board', event.target.value)} aria-label="Actual board model" /></label></div>
    <div className="notice"><p>Prefilled values come from the selected source, not a measurement. Enter actual workspace and rope limits. The margin-adjusted region must include (0,0), stay below the anchors, and retain tension. Values differing from the selected firmware can be saved unverified for Phase 5 reconciliation.</p></div>
    <div className="form-grid measurements-grid">{numbers.map(([key, label]) => <label className="form-field" key={key}>{label}<input type="number" step="any" value={values[key]} onChange={event => change(key, event.target.value)} aria-label={label} /></label>)}</div>
    <label className="form-field">Measured by<input value={values.measured_by} onChange={event => change('measured_by', event.target.value)} /></label><label className="form-field">Measurement and workspace-test notes<textarea rows={3} value={values.measurement_notes} onChange={event => change('measurement_notes', event.target.value)} /></label><label className="form-field">Manual origin procedure before every job<textarea rows={3} value={values.origin_procedure} onChange={event => change('origin_procedure', event.target.value)} /></label>
    {([['firmware_matches_measurements', 'I confirmed the flashed firmware uses these calibration values.'], ['pen_lift_and_holding_tested', 'I tested pen clearance/settling and motor holding with this machine.'], ['workspace_tested', 'I tested the recorded work area and rope-length limits.'], ['verified', 'Mark this profile verified by my recorded checks.']] as const).map(([key, label]) => <label key={key} className="checkbox-control"><input type="checkbox" checked={checks[key]} onChange={event => setChecks(current => ({ ...current, [key]: event.target.checked }))} />{label}</label>)}
    {error && <p className="form-error" role="alert">{error}</p>}<button className="primary-button dialog-done" disabled={busy} onClick={() => void submit()}><Ruler size={16} />Save & select {checks.verified ? 'verified' : 'unverified'} profile</button>
  </dialog>;
}
