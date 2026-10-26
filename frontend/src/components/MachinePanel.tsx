import { useEffect, useState } from 'react';
import { Home, Plug, RefreshCw, Square, Unplug } from 'lucide-react';
import { connectMachine, controlMachine, disconnectMachine, fetchPorts, homeMachine } from '../api/client';
import type { CalibrationProfile, MachineState, PortsResponse } from '../api/contracts';
import { UsbRunCard, runActive } from './UsbRunCard';

const labels: Record<string, string> = { disconnected: 'Not connected', connecting: 'Connecting', connected: 'Connected', incompatible: 'Incompatible firmware', lost: 'Connection lost' };

export function HomeControl({ machine, refresh }: { machine: MachineState; refresh: () => Promise<void> }) {
  const [confirmed, setConfirmed] = useState(false); const [message, setMessage] = useState('');
  const status = machine.status;
  if (!status || machine.connection !== 'connected') return null;
  const atOrigin = status.position_mm[0] === 0 && status.position_mm[1] === 0;
  if (atOrigin || status.origin === 'UNSET') return null;
  return <div className="home-control"><label className="checkbox-control"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />The straight pen-up route from ({status.position_mm[0].toFixed(1)}, {status.position_mm[1].toFixed(1)}) to (0,0) is clear.</label>
    <button className="subtle-button" disabled={!confirmed || status.state !== 'IDLE'} onClick={() => void homeMachine({ expected_boot_id: status.boot_id, expected_origin_revision: status.origin_revision, route_confirmed: true }).then(refresh).then(() => { setConfirmed(false); setMessage('Go to origin requested. The firmware validates the route before moving.'); }).catch(error => setMessage(error.message))}><Home size={13} />Go to origin</button>
    {message && <p className="muted-copy" role="status">{message}</p>}</div>;
}

/** Port choice and explicit connect. Listing never opens a port. */
export function PortPicker({ refresh }: { refresh: () => Promise<void> }) {
  const [ports, setPorts] = useState<PortsResponse | null>(null);
  const [port, setPort] = useState(''); const [busy, setBusy] = useState(false); const [message, setMessage] = useState('');
  const loadPorts = () => fetchPorts().then(result => { setPorts(result); setPort(current => current || result.ports.find(item => item.likely_arduino)?.device || result.ports[0]?.device || ''); }).catch(error => setMessage(error.message));
  useEffect(() => { void loadPorts(); }, []);
  const connect = async () => { setBusy(true); setMessage(''); try { await connectMachine(port); await refresh(); } catch (error) { setMessage(error instanceof Error ? error.message : 'Machine request failed.'); } finally { setBusy(false); } };
  const selected = ports?.ports.find(item => item.device === port);
  return <>
    <div className="port-row"><select aria-label="Serial port" value={port} disabled={busy} onChange={event => setPort(event.target.value)}><option value="">{ports?.ports.length ? 'Select a port' : 'No ports found'}</option>{ports?.ports.map(item => <option key={item.device} value={item.device}>{item.simulated ? '⚠ ' : ''}{item.description}{item.simulated ? '' : ` · ${item.device}`}{item.accessible === false ? ' · no permission' : ''}</option>)}</select>
      <button className="icon-button" aria-label="Refresh ports" disabled={busy} onClick={() => void loadPorts()}><RefreshCw size={14} /></button></div>
    {selected?.accessible === false && <p className="form-error">This account cannot open {selected.device}. Run <code>sudo usermod -aG dialout $USER</code>, then log out and back in.</p>}
    <button className="outline-button" disabled={busy || !port} onClick={() => void connect()}><Plug size={13} /> {busy ? 'Waiting for handshake…' : 'Connect'}</button>
    <p className="muted-copy">Listing ports does not open them. Connecting opens only the selected port and sends read-only HELLO/STATUS frames; it never moves the machine.</p>
    {ports?.error && <p className="muted-copy">{ports.error}</p>}
    {message && <p className="form-error" role="alert">{message}</p>}
  </>;
}

export function MachinePanel({ machine, refresh, profile }: { machine: MachineState | null; refresh: () => Promise<void>; profile?: CalibrationProfile }) {
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState('');
  const run = async (operation: () => Promise<unknown>) => { setBusy(true); setMessage(''); try { await operation(); await refresh(); } catch (error) { setMessage(error instanceof Error ? error.message : 'Machine request failed.'); } finally { setBusy(false); } };
  const connected = machine?.connection === 'connected';
  const status = machine?.status; const hello = machine?.hello;
  const configMatches = !!hello && !!profile?.firmware_config_id && profile.firmware_config_id === hello.config_id;
  return <section className="machine-panel" aria-labelledby="machine-panel-title">
    <div className="section-heading"><h3 id="machine-panel-title">USB machine</h3><span className={`small-tag connection-${machine?.connection ?? 'unknown'}`}>{labels[machine?.connection ?? ''] ?? 'Service offline'}</span></div>
    {!connected ? <PortPicker refresh={refresh} /> : <>
      <dl className="path-insights machine-details">
        <div><dt>Firmware</dt><dd>{hello?.firmware_version} · protocol {hello?.protocol}{machine?.simulated && machine.port?.startsWith('sim://') ? ' · simulated' : ''}</dd></div>
        <div><dt>Configuration</dt><dd className={configMatches ? 'match' : 'mismatch'}>{hello?.config_id} {configMatches ? '✓ profile' : '≠ profile'}</dd></div>
        <div><dt>Session</dt><dd>boot {status?.boot_id} · origin rev {status?.origin_revision}</dd></div>
        <div><dt>Origin</dt><dd>{status?.origin === 'UNSET' ? 'Not set — use the keypad' : status?.origin === 'FRESH' ? 'Confirmed' : 'Referenced'}</dd></div>
        <div><dt>Device</dt><dd>{status?.state} · pen {status?.pen_down ? 'down' : 'up'}</dd></div>
        <div><dt>Commanded position</dt><dd>{status ? `${status.position_mm[0].toFixed(3)}, ${status.position_mm[1].toFixed(3)} mm` : '—'}</dd></div>
        <div><dt>Last result</dt><dd>{status ? `${status.result}${status.reason !== 'NONE' ? ` · ${status.reason}` : ''}` : '—'}</dd></div>
      </dl>
      {machine && <HomeControl machine={machine} refresh={refresh} />}
      {status && ['RUNNING', 'PAUSING', 'PAUSED', 'RESUMING'].includes(status.state) && !runActive(machine?.run) && <button className="subtle-button stop-button" onClick={() => void run(() => controlMachine('stop'))}><Square size={13} />Stop machine job</button>}
      <button className="subtle-button" disabled={busy} onClick={() => void run(disconnectMachine)}><Unplug size={13} />Disconnect</button>
    </>}
    {machine?.message && <p className="muted-copy machine-message">{machine.message}</p>}
    {message && <p className="form-error" role="alert">{message}</p>}
    {machine?.run && <UsbRunCard run={machine.run} refresh={refresh} />}
  </section>;
}
