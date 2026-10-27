import { ChevronDown, Download } from 'lucide-react';
import { usePopover } from './Popover';

export type DownloadFormat = 'gcode' | 'svg' | 'png';

const formats: [DownloadFormat, string][] = [['gcode', 'G-code'], ['svg', 'SVG'], ['png', 'PNG']];

/** Export G-code directly; SVG and PNG sit behind the chevron. */
export function ExportMenu({ blocked, download }: { blocked: string; download: (format: DownloadFormat) => void }) {
  const { open, setOpen, root } = usePopover();
  return <div className="export-control" ref={root}>
    <button className="export-main" disabled={!!blocked} title={blocked || 'Download this revision as G-code'} onClick={() => download('gcode')}>
      <Download size={20} /><span className="button-label">Export G-code</span></button>
    <button className="export-more" aria-label="More export options" aria-expanded={open} aria-controls="export-options" onClick={() => setOpen(!open)}><ChevronDown size={17} /></button>
    {open && <div className="popover export-popover" id="export-options" data-popover>
      <p className="popover-label">Download as</p>
      <div className="popover-formats">{formats.map(([format, label]) =>
        <button key={format} disabled={!!blocked} onClick={() => { setOpen(false); download(format); }}>{label}</button>)}</div>
      {blocked && <p className="popover-note">{blocked}.</p>}
    </div>}
  </div>;
}
