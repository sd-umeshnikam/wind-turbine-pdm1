import "./StatTile.css";

interface StatTileProps {
  label: string;
  value: string;
  sublabel?: string;
  accent?: string;
}

export function StatTile({ label, value, sublabel, accent }: StatTileProps) {
  return (
    <div className="stat-tile" style={accent ? { borderTopColor: accent } : undefined}>
      <div className="stat-tile-label">{label}</div>
      <div className="stat-tile-value">{value}</div>
      {sublabel && <div className="stat-tile-sublabel">{sublabel}</div>}
    </div>
  );
}
