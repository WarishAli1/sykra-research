export function RelevanceStack({ score }: { score: number | null | undefined }) {
  const pct = score ?? 0;
  const bars = 8;
  const filled = Math.round(pct * bars);

  return (
    <span
      className="citation-stack"
      title={`Relevance ${(pct * 100).toFixed(0)}%`}
      aria-label={`Relevance score ${(pct * 100).toFixed(0)} percent`}
    >
      {Array.from({ length: bars }).map((_, i) => (
        <span
          key={i}
          className={i < filled ? "active" : ""}
          style={{ height: `${((i + 1) / bars) * 100}%` }}
        />
      ))}
    </span>
  );
}
