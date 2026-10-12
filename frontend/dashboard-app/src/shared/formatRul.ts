// Calendar-approximate: 30-day months, 365-day years. Shows the two largest non-zero units.
export function formatRul(hours: number): string {
  if (hours < 24) return `${Math.max(0, Math.round(hours))} h`;
  const totalDays = Math.round(hours / 24);
  const years = Math.floor(totalDays / 365);
  const months = Math.floor((totalDays % 365) / 30);
  const days = (totalDays % 365) % 30;
  const parts = [
    years ? `${years} ${years === 1 ? "year" : "years"}` : "",
    months ? `${months} ${months === 1 ? "month" : "months"}` : "",
    days ? `${days} ${days === 1 ? "day" : "days"}` : "",
  ].filter(Boolean);
  return parts.slice(0, 2).join(" ") || "0 days";
}
