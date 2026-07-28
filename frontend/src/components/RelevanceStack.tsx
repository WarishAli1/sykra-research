export function RelevanceStack({
  score,
}: {
  score: number | null |undefined;
}) {
  const value = score ?? 0;

  const bars = 8;

  const filled = Math.round(value * bars);

  const label =
    value >= 0.85
      ? "Excellent"
      : value >= 0.65
      ? "High"
      : value >= 0.45
      ? "Medium"
      : value > 0
      ? "Low"
      : "N/A";

  return (
    <div
      className="group flex items-center gap-2"
      title={`Relevance ${(value * 100).toFixed(0)}%`}
      aria-label={`Relevance ${(value * 100).toFixed(0)} percent`}
    >
      <div className="flex h-4 items-end gap-[3px]">
        {Array.from({ length: bars }).map((_, i) => (
          <span
            key={i}
            className={`w-[3px] rounded-full transition-all duration-300 ${
              i < filled
                ? "bg-gradient-to-t from-indigo to-gold"
                : "bg-[#E7ECE9]"
            }`}
            style={{
              height: `${30 + ((i + 1) / bars) * 70}%`,
            }}
          />
        ))}
      </div>

      <span className="text-[10.5px] font-medium text-ink-soft transition-colors group-hover:text-indigo">
        {label}
      </span>
    </div>
  );
}