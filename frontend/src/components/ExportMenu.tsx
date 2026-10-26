import { ArrowRight, ChevronDown, Download, FlaskConical } from 'lucide-react';
import { usePopover } from './Popover';

export type DownloadFormat = 'json' | 'svg' | 'gcode';

/** Export G-code directly; the other draft formats and machine-file workflows sit behind the chevron. */
export function ExportMenu({ blocked, download, testExport, prepare, physicalReady }: {
  blocked: string; download: (format: DownloadFormat) => void; testExport: () => void; prepare: () => void; physicalReady: boolean;
}) {
  const { open, setOpen, root } = usePopover();
  const pick = (action: () => void) => { setOpen(false); action(); };
  return <div className="export-control" ref={root}>
    <button className="export-main" disabled={!!blocked} title={blocked || 'Download the exact, unverified G-code for this revision'} onClick={() => download('gcode')}>
      <Download size={20} /><span className="button-label">Export G-code</span></button>
    <button className="export-more" aria-label="More export options" aria-expanded={open} aria-controls="export-options" onClick={() => setOpen(!open)}><ChevronDown size={17} /></button>
    {open && <div className="popover export-popover" id="export-options" data-popover>
      <p className="popover-label">Download this revision</p>
      <div className="popover-formats">
        <button disabled={!!blocked} onClick={() => pick(() => download('json'))}>Draft JSON</button>
        <button disabled={!!blocked} onClick={() => pick(() => download('svg'))}>SVG</button>
        <button disabled={!!blocked} onClick={() => pick(() => download('gcode'))}>G-code</button>
      </div>
      {blocked && <p className="popover-note">{blocked}.</p>}
      <p className="popover-label">Machine files</p>
      <button className="popover-item" disabled={!!blocked} onClick={() => pick(testExport)}><FlaskConical size={17} /><span>Test export without hardware<small>Verified copy to a test directory</small></span></button>
      <button className="popover-item" disabled={!!blocked || !physicalReady} onClick={() => pick(prepare)}
        title={physicalReady ? 'Prepare against the selected measured profile' : 'Record and verify a measured profile in the Machine tab first'}>
        <ArrowRight size={17} /><span>Prepare for drawing<small>{physicalReady ? 'SD workflow with the verified profile' : 'Needs a verified machine profile'}</small></span></button>
      <p className="popover-note">Downloads are drafts. Nothing reaches the machine from here.</p>
    </div>}
  </div>;
}
