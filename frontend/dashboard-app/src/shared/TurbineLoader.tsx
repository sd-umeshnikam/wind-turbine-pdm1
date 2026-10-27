import "./TurbineLoader.css";

// Loading indicator: a wind turbine whose blades spin. Colours come from theme tokens,
// and the spin stops for users who ask for reduced motion (see index.css).
export function TurbineLoader({ label = "Loading…", size = 72 }: { label?: string; size?: number }) {
  return (
    <div className="turbine-loader" role="status" aria-live="polite">
      <svg width={size} height={size * 1.25} viewBox="0 0 80 100" aria-hidden="true">
        <path className="turbine-loader-tower" d="M38.5 30h3l2.5 66h-8z" />
        <rect className="turbine-loader-base" x="28" y="94" width="24" height="3" rx="1.5" />
        <rect className="turbine-loader-nacelle" x="34" y="25" width="16" height="7" rx="3.5" />
        <g className="turbine-loader-rotor">
          {[0, 120, 240].map((deg) => (
            <path
              key={deg}
              className="turbine-loader-blade"
              d="M40 28 C37.5 22 37.8 8 40 2 C42.2 8 42.5 22 40 28 Z"
              transform={`rotate(${deg} 40 28)`}
            />
          ))}
          <circle className="turbine-loader-hub" cx="40" cy="28" r="3.2" />
        </g>
      </svg>
      <span className="turbine-loader-label">{label}</span>
    </div>
  );
}
