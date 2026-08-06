import { Link } from "react-router-dom";
import type { QuestionSource } from "../api/useQuestion";

interface SourceChipProps {
  source: QuestionSource;
}

const urgencyDot: Record<string, string> = {
  critical: "bg-red-500",
  high: "bg-orange-400",
  normal: "bg-slate-400",
};

// Claim.urgency is nullable in the database, so a retrieved claim can arrive
// without one. Same defensive shape UrgencyDonut already uses: a neutral dot
// beats a missing one, which reads as a rendering bug.
const UNKNOWN_URGENCY_DOT = "bg-slate-300";

export default function SourceChip({ source }: SourceChipProps) {
  const dot = (source.urgency && urgencyDot[source.urgency]) || UNKNOWN_URGENCY_DOT;

  return (
    <Link
      to={`/kuyruk?claim_id=${source.claim_id}`}
      className="block p-2 rounded border border-slate-200 bg-white hover:border-blue-400 transition-colors"
    >
      <div className="flex items-center gap-2 mb-1">
        <span className={`inline-block w-2 h-2 rounded-full ${dot}`} />
        <span className="text-xs font-medium text-slate-700">
          #{source.claim_id}
          {source.external_ref ? ` (${source.external_ref})` : ""}
        </span>
        {source.score != null && (
          <span className="text-xs text-slate-400 ml-auto">
            {(source.score * 100).toFixed(0)}%
          </span>
        )}
      </div>
      <p className="text-xs text-slate-500 truncate">{source.snippet}</p>
      {source.incident_date && (
        <p className="text-xs text-slate-400 mt-0.5">{source.incident_date}</p>
      )}
    </Link>
  );
}