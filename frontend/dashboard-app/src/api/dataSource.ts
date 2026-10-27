// Tracks which data areas fell back to built-in demo data, so the UI can say so
// instead of silently presenting mock numbers as real.
type Listener = (areas: string[]) => void;

const demoAreas = new Set<string>();
const listeners = new Set<Listener>();

export function reportDemoData(area: string, err: unknown): void {
  if (!demoAreas.has(area)) {
    console.warn(`Using demo data for ${area}:`, err);
    demoAreas.add(area);
    listeners.forEach((l) => l([...demoAreas]));
  }
}

export function subscribeDemoData(listener: Listener): () => void {
  listeners.add(listener);
  listener([...demoAreas]);
  return () => listeners.delete(listener);
}
