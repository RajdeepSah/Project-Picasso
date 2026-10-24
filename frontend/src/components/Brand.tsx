export function Brand({ compact = false }: { compact?: boolean }) {
  return <div className="brand">
    <svg className="brand-mark" viewBox="0 0 36 36" fill="none" aria-hidden="true">
      <rect width="36" height="36" rx="11" fill="currentColor" />
      <path d="M11 26V10H19C24 10 26 17 21 20L16 22M16 15L23 26" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
    {!compact && <span>picasso<span className="brand-caption">DRAWING STUDIO</span></span>}
  </div>;
}
