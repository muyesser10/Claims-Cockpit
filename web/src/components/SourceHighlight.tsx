import type { SourceReference } from "../api/useQueue";

interface SourceHighlightProps {
  text: string;
  activeRef: SourceReference | null | undefined;
}

export default function SourceHighlight({ text, activeRef }: SourceHighlightProps) {
  if (!activeRef || activeRef.start == null || activeRef.end == null) {
    return <>{text}</>;
  }

  const { start, end } = activeRef;
  if (start < 0 || end > text.length || start >= end) {
    return <>{text}</>;
  }

  return (
    <>
      {text.slice(0, start)}
      <mark className="bg-yellow-300 rounded px-0.5">{text.slice(start, end)}</mark>
      {text.slice(end)}
    </>
  );
}