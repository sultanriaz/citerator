const EXAMPLES = [
  "When is enhanced due diligence required?",
  "How long must transaction records be kept?",
  "What triggers a suspicious activity report?",
  "What are the requirements for identifying beneficial owners?",
];

export interface ExampleChipsProps {
  onSelect: (question: string) => void;
}

export function ExampleChips({ onSelect }: ExampleChipsProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {EXAMPLES.map((q) => (
        <button
          key={q}
          type="button"
          onClick={() => onSelect(q)}
          className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-secondary hover:border-accent hover:text-primary transition-colors"
        >
          {q}
        </button>
      ))}
    </div>
  );
}