// Busy indicator: a wind turbine whose rotor turns while work is in progress. Static when the
// user prefers reduced motion; the label is always shown, so the state never relies on motion.

const BLADE = "M30.2 21 Q29.4 9 31.2 2.5 Q33.6 2 34.2 5 L33.8 21 Z";

export function TurbineLoader({ label, size = 52 }: { label: string; size?: number }) {
  return (
    <div className="turbine-loader" role="status" aria-live="polite">
      <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" focusable="false">
        <path className="turbine-tower" d="M30.4 24 L33.6 24 L35.6 62 L28.4 62 Z" />
        <rect className="turbine-tower" x="30" y="19" width="10" height="6" rx="2" />
        <g className="turbine-rotor">
          {[0, 120, 240].map((a) => (
            <path key={a} d={BLADE} transform={`rotate(${a} 32 22)`} />
          ))}
        </g>
        <circle cx="32" cy="22" r="3.2" className="turbine-hub" />
      </svg>
      <span>{label}</span>
    </div>
  );
}
