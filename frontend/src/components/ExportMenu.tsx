import { ChevronDown, Download } from 'lucide-react';
import { usePopover } from './Popover';

export type DownloadFormat = 'gcode' | 'svg' | 'png' | 'txt';

const formats: [DownloadFormat, string, string][] = [
  ['gcode', 'G-code', 'G-code for the drawbot (.nc)'], ['svg', 'SVG', 'Vector preview (.svg)'],
  ['png', 'PNG', 'Raster preview (.png)'], ['txt', 'TXT', 'G-code as plain text (.txt)'],
];

/** Export G-code directly; SVG, PNG and plain-text G-code sit behind the chevron. */
export function ExportMenu({ blocked, download }: { blocked: string; download: (format: DownloadFormat) => void }) {
  const { open, setOpen, root } = usePopover();
  return <div className="export-control" ref={root}>
    <button className="export-main" disabled={!!blocked} title={blocked || 'Download this revision as G-code'} onClick={() => download('gcode')}>
      <Download size={20} /><span className="button-label">Export G-code</span></button>
    <button className="export-more" aria-label="More export options" aria-expanded={open} aria-controls="export-options" onClick={() => setOpen(!open)}><ChevronDown size={17} /></button>
    {open && <div className="popover export-popover" id="export-options" data-popover>
      <p className="popover-label">Download as</p>
      <div className="popover-formats">{formats.map(([format, label, hint]) =>
        <button key={format} disabled={!!blocked} title={hint} onClick={() => { setOpen(false); download(format); }}>{label}</button>)}</div>
      {blocked && <p className="popover-note">{blocked}.</p>}
    </div>}
  </div>;
}
