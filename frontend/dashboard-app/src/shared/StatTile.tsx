import "./StatTile.css";

interface StatTileProps {
  label: string;
  value: string;
  sublabel?: string;
  accent?: string;
}

export function StatTile({ label, value, sublabel, accent }: StatTileProps) {
  return (
    <div
      className="stat-tile"
      data-accent={accent ? "" : undefined}
      style={accent ? ({ "--stat-accent": accent } as React.CSSProperties) : undefined}
    >
      <div className="stat-tile-label">{label}</div>
      <div className="stat-tile-value">{value}</div>
      {sublabel && <div className="stat-tile-sublabel">{sublabel}</div>}
    </div>
  );
}
