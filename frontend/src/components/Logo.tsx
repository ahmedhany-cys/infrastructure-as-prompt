export function Logo({ className = "h-7 w-7" }: { className?: string }) {
  // Three stacked layers: request -> requirements -> infrastructure.
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <defs>
        <linearGradient id="iap-logo-bg" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#6366f1" />
          <stop offset="1" stopColor="#0d9488" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="url(#iap-logo-bg)" />
      <path d="M8 11.5 16 8l8 3.5-8 3.5z" fill="#ffffff" />
      <path d="m8 16 8 3.5 8-3.5" fill="none" stroke="#e0e7ff" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
      <path d="m8 20.5 8 3.5 8-3.5" fill="none" stroke="#99f6e4" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
