export function Brand({ compact = false }: { compact?: boolean }) {
  return <div className="brand">
    <svg className="brand-mark" viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path d="M21.2 5.6a3.1 3.1 0 0 1 4.4 4.4L11.2 24.4l-5.7 1.9 1.9-5.7z" fill="var(--lime)" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="M18.6 8.2l4.4 4.4M7.4 20.6l3.8 3.8M17.5 27h8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
    {!compact && <span className="brand-name">picasso</span>}
  </div>;
}
