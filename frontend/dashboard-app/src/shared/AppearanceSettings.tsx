import { useEffect, useRef, useState } from "react";
import {
  ACCENT_PRESETS,
  DEFAULT_APPEARANCE,
  applyAppearance,
  loadAppearance,
  saveAppearance,
  type Appearance,
} from "../config/appearance";
import { IconSliders } from "./icons";
import "./AppearanceSettings.css";

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <fieldset className="appearance-field">
      <legend>{label}</legend>
      <div className="segmented" role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={value === o.value}
            className={value === o.value ? "active" : ""}
            onClick={() => onChange(o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

export function AppearanceSettings() {
  const [open, setOpen] = useState(false);
  const [appearance, setAppearance] = useState<Appearance>(loadAppearance);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    applyAppearance(appearance);
    saveAppearance(appearance);
  }, [appearance]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const update = (patch: Partial<Appearance>) => setAppearance((a) => ({ ...a, ...patch }));

  return (
    <div className="appearance" ref={panelRef}>
      <button
        type="button"
        className="appearance-trigger"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((o) => !o)}
      >
        <IconSliders />
        Appearance
      </button>

      {open && (
        <div className="appearance-panel" role="dialog" aria-label="Appearance settings">
          <Segmented
            label="Theme"
            value={appearance.theme}
            options={[
              { value: "system", label: "System" },
              { value: "light", label: "Light" },
              { value: "dark", label: "Dark" },
            ]}
            onChange={(theme) => update({ theme })}
          />

          <fieldset className="appearance-field">
            <legend>Accent colour</legend>
            <div className="swatches">
              {ACCENT_PRESETS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  className={`swatch${appearance.accent === p.value ? " active" : ""}`}
                  style={{ background: p.value }}
                  aria-label={p.name}
                  aria-pressed={appearance.accent === p.value}
                  title={p.name}
                  onClick={() => update({ accent: p.value })}
                />
              ))}
              <label className="swatch custom" title="Custom colour">
                <input
                  type="color"
                  value={appearance.accent}
                  aria-label="Custom accent colour"
                  onChange={(e) => update({ accent: e.target.value })}
                />
              </label>
            </div>
          </fieldset>

          <Segmented
            label="Density"
            value={appearance.density}
            options={[
              { value: "comfortable", label: "Comfortable" },
              { value: "compact", label: "Compact" },
            ]}
            onChange={(density) => update({ density })}
          />

          <Segmented
            label="Text size"
            value={appearance.fontScale}
            options={[
              { value: "default", label: "Default" },
              { value: "large", label: "Large" },
            ]}
            onChange={(fontScale) => update({ fontScale })}
          />

          <button type="button" className="btn appearance-reset" onClick={() => setAppearance(DEFAULT_APPEARANCE)}>
            Reset to defaults
          </button>
        </div>
      )}
    </div>
  );
}
