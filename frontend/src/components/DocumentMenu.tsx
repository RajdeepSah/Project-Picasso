import { Check, ChevronDown, History, Layers, Plus, Settings2 } from 'lucide-react';
import type { DrawingDraft } from '../api/contracts';
import { usePopover } from './Popover';

/** The current drawing's title, opening new-drawing, recently viewed revisions and studio information. */
export function DocumentMenu({ draft, session, open: reopen, newDrawing, browse, info }: {
  draft: DrawingDraft | null; session: DrawingDraft[]; open: (id: string) => void;
  newDrawing: () => void; browse: () => void; info: () => void;
}) {
  const { open, setOpen, root } = usePopover();
  const pick = (action: () => void) => { setOpen(false); action(); };
  return <div className="document-menu" ref={root}>
    <button className="document-title" aria-expanded={open} aria-controls="document-options" onClick={() => setOpen(!open)}>
      <span className="document-name">{draft?.title ?? 'Untitled drawing'}</span><span className="sr-only">, drawing options</span><ChevronDown size={20} /></button>
    {open && <div className="popover document-popover" id="document-options" data-popover>
      <button className="popover-item" onClick={() => pick(newDrawing)}><Plus size={17} /><span>New drawing</span></button>
      <p className="popover-label">Recently viewed · saved</p>
      {session.length ? session.map(item => <button key={item.revision_id} className="popover-item" aria-current={item.revision_id === draft?.revision_id ? 'true' : undefined} onClick={() => pick(() => reopen(item.revision_id))}>
        <Layers size={17} /><span>{item.title}<small>Revision {item.revision} · seed {item.spec.seed ?? 0}</small></span>{item.revision_id === draft?.revision_id && <Check size={15} className="popover-check" />}</button>)
        : <p className="popover-note">Drawings you create or open this session appear here.</p>}
      <div className="popover-rule" />
      <button className="popover-item" onClick={() => pick(browse)}><History size={17} /><span>Browse saved history</span></button>
      <button className="popover-item" onClick={() => pick(info)}><Settings2 size={17} /><span>Studio information</span></button>
    </div>}
  </div>;
}
