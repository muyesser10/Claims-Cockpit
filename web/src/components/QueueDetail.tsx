import { useState, type ReactNode } from "react";
import SourceHighlight from "./SourceHighlight";
import type {
  Claim,
  ClaimEdits,
  ClaimExtraction,
  DamageType,
  ValidationFlag,
} from "../api/useQueue";

interface QueueDetailProps {
  claim: Claim;
  onApprove: (edits?: ClaimEdits) => void;
  onReject: () => void;
  isSubmitting: boolean;
}

const damageTypeOptions: { value: DamageType; label: string }[] = [
  { value: "collision", label: "Çarpışma" },
  { value: "single_vehicle", label: "Tek Araç" },
  { value: "glass", label: "Cam" },
  { value: "hail", label: "Dolu" },
  { value: "fire", label: "Yangın" },
  { value: "theft", label: "Hırsızlık" },
  { value: "animal", label: "Hayvan" },
  { value: "other", label: "Diğer" },
];

// Extraction fields the operator may correct — mirrors api/routers/queue.py's
// EDITABLE_FIELDS. Used both to build the edit diff and to tell which
// validation flags belong next to a rendered field vs. the leftover list.
const RENDERED_FIELDS = new Set([
  "policy_no",
  "plate",
  "incident_date",
  "damage_type",
  "injury",
  "counterparty_exists",
  "estimated_amount",
  "damage_description",
  "incident_location.city",
  "incident_location.district",
]);

// injury/counterparty_exists are bool | null, and null ("unspecified" — the
// text never said) must stay distinct from false ("the text said no").
type TriState = "unspecified" | "true" | "false";

function toTriState(value: boolean | null | undefined): TriState {
  if (value === true) return "true";
  if (value === false) return "false";
  return "unspecified";
}

function fromTriState(value: TriState): boolean | null {
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
}

interface FormState {
  policy_no: string;
  plate: string;
  incident_date: string;
  damage_type: DamageType | "";
  injury: TriState;
  counterparty_exists: TriState;
  estimated_amount: string;
  damage_description: string;
  city: string;
  district: string;
}

function toFormState(extraction: ClaimExtraction): FormState {
  return {
    policy_no: extraction.policy_no ?? "",
    plate: extraction.plate ?? "",
    incident_date: extraction.incident_date ?? "",
    damage_type: extraction.damage_type ?? "",
    injury: toTriState(extraction.injury),
    counterparty_exists: toTriState(extraction.counterparty_exists),
    estimated_amount:
      extraction.estimated_amount != null ? String(extraction.estimated_amount) : "",
    damage_description: extraction.damage_description ?? "",
    city: extraction.incident_location?.city ?? "",
    district: extraction.incident_location?.district ?? "",
  };
}

// Never rendered into a form (the "extraction hatası" branch shows no
// inputs), but useState needs a starting value regardless of extraction.
const EMPTY_FORM: FormState = {
  policy_no: "",
  plate: "",
  incident_date: "",
  damage_type: "",
  injury: "unspecified",
  counterparty_exists: "unspecified",
  estimated_amount: "",
  damage_description: "",
  city: "",
  district: "",
};

const inputClass = "w-full rounded border border-slate-300 px-2 py-1 text-sm";

function FieldWrapper({
  label,
  field,
  flags,
  onActivate,
  children,
}: {
  label: string;
  field: string;
  flags: ValidationFlag[];
  onActivate: (field: string | null) => void;
  children: ReactNode;
}) {
  const fieldFlags = flags.filter((flag) => flag.field === field);
  return (
    <div
      className="mb-3"
      onFocus={() => onActivate(field)}
      onBlur={() => onActivate(null)}
    >
      <label className="block text-xs font-medium text-slate-600 mb-1">{label}</label>
      {children}
      {fieldFlags.length > 0 && (
        <ul className="mt-1 space-y-0.5">
          {fieldFlags.map((flag) => (
            <li key={flag.rule} className="text-xs text-amber-700">
              ⚠ {flag.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function QueueDetail({
  claim,
  onApprove,
  onReject,
  isSubmitting,
}: QueueDetailProps) {
  const extraction = claim.data.extraction;
  const flags = claim.data.validation_flags ?? [];
  const unmatchedFlags = flags.filter((flag) => !RENDERED_FIELDS.has(flag.field));

  const [form, setForm] = useState<FormState>(() =>
    extraction ? toFormState(extraction) : EMPTY_FORM,
  );
  const [confirmingReject, setConfirmingReject] = useState(false);
  const [activeField, setActiveField] = useState<string | null>(null);

  function update<K extends keyof FormState>(field: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function handleApprove() {
    if (!extraction) {
      onApprove();
      return;
    }

    const initial = toFormState(extraction);
    const edits: ClaimEdits = {};

    if (form.policy_no !== initial.policy_no) edits.policy_no = form.policy_no || null;
    if (form.plate !== initial.plate) edits.plate = form.plate || null;
    if (form.incident_date !== initial.incident_date) {
      edits.incident_date = form.incident_date || null;
    }
    if (form.damage_type !== initial.damage_type) edits.damage_type = form.damage_type || null;
    if (form.injury !== initial.injury) edits.injury = fromTriState(form.injury);
    if (form.counterparty_exists !== initial.counterparty_exists) {
      edits.counterparty_exists = fromTriState(form.counterparty_exists);
    }
    if (form.estimated_amount !== initial.estimated_amount) {
      edits.estimated_amount = form.estimated_amount === "" ? null : Number(form.estimated_amount);
    }
    if (form.damage_description !== initial.damage_description) {
      edits.damage_description = form.damage_description || null;
    }
    if (form.city !== initial.city) edits["incident_location.city"] = form.city || null;
    if (form.district !== initial.district) {
      edits["incident_location.district"] = form.district || null;
    }

    onApprove(Object.keys(edits).length > 0 ? edits : undefined);
  }

  return (
    <div className="p-4 rounded-lg border border-slate-200 bg-white">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-medium text-slate-700">İhbar #{claim.id}</h2>
        <span className="text-xs text-slate-400">{claim.channel}</span>
      </div>

      <div className="mb-4 p-2 rounded bg-slate-50 text-xs text-slate-500 max-h-24 overflow-y-auto">
  <SourceHighlight
    text={claim.data.masked_text}
    activeRef={activeField ? extraction?.source_references[activeField] : null}
  />
</div>
      <div className="mb-4">
        {flags.length === 0 ? (
          <p className="text-sm text-green-700">Doğrulama uyarısı yok.</p>
        ) : (
          <p className="text-sm text-amber-700">
            {flags.length} doğrulama uyarısı var, ilgili alanları kontrol edin.
          </p>
        )}
        {unmatchedFlags.length > 0 && (
          <div className="mt-1 space-y-0.5">
            {unmatchedFlags.map((flag) => (
              <p key={`${flag.field}-${flag.rule}`} className="text-xs text-amber-700">
                ⚠ [{flag.field}] {flag.message}
              </p>
            ))}
          </div>
        )}
      </div>

      {!extraction ? (
        <p className="text-sm text-red-600 mb-4">Çıkarım yapılamadı (extraction hatası).</p>
      ) : (
        <div className="mb-4">
          <FieldWrapper label="Poliçe No" field="policy_no" flags={flags} onActivate={setActiveField}>
            <input
              className={inputClass}
              value={form.policy_no}
              onChange={(e) => update("policy_no", e.target.value)}
            />
          </FieldWrapper>
          <FieldWrapper label="Plaka" field="plate" flags={flags} onActivate={setActiveField}>
            <input
              className={inputClass}
              value={form.plate}
              onChange={(e) => update("plate", e.target.value)}
            />
          </FieldWrapper>
          <FieldWrapper label="Olay Tarihi" field="incident_date" flags={flags} onActivate={setActiveField}>
            <input
              type="date"
              className={inputClass}
              value={form.incident_date}
              onChange={(e) => update("incident_date", e.target.value)}
            />
          </FieldWrapper>
          <FieldWrapper label="Hasar Türü" field="damage_type" flags={flags} onActivate={setActiveField}>
            <select
              className={inputClass}
              value={form.damage_type}
              onChange={(e) => update("damage_type", e.target.value as DamageType | "")}
            >
              <option value="">Belirtilmemiş</option>
              {damageTypeOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </FieldWrapper>
          <FieldWrapper label="Yaralanma" field="injury" flags={flags} onActivate={setActiveField}>
            <select
              className={inputClass}
              value={form.injury}
              onChange={(e) => update("injury", e.target.value as TriState)}
            >
              <option value="unspecified">Belirtilmemiş</option>
              <option value="true">Evet</option>
              <option value="false">Hayır</option>
            </select>
          </FieldWrapper>
          <FieldWrapper label="Karşı Taraf Var mı" field="counterparty_exists" flags={flags} onActivate={setActiveField}>
            <select
              className={inputClass}
              value={form.counterparty_exists}
              onChange={(e) => update("counterparty_exists", e.target.value as TriState)}
            >
              <option value="unspecified">Belirtilmemiş</option>
              <option value="true">Evet</option>
              <option value="false">Hayır</option>
            </select>
          </FieldWrapper>
          <FieldWrapper label="Tahmini Tutar" field="estimated_amount" flags={flags} onActivate={setActiveField}>
            <input
              type="number"
              className={inputClass}
              value={form.estimated_amount}
              onChange={(e) => update("estimated_amount", e.target.value)}
            />
          </FieldWrapper>
          <FieldWrapper label="Hasar Açıklaması" field="damage_description" flags={flags} onActivate={setActiveField}>
            <textarea
              className={inputClass}
              rows={2}
              value={form.damage_description}
              onChange={(e) => update("damage_description", e.target.value)}
            />
          </FieldWrapper>
          <FieldWrapper label="İl" field="incident_location.city" flags={flags} onActivate={setActiveField}>
            <input
              className={inputClass}
              value={form.city}
              onChange={(e) => update("city", e.target.value)}
            />
          </FieldWrapper>
          <FieldWrapper label="İlçe" field="incident_location.district" flags={flags} onActivate={setActiveField}>
            <input
              className={inputClass}
              value={form.district}
              onChange={(e) => update("district", e.target.value)}
            />
          </FieldWrapper>
        </div>
      )}

      <div className="flex gap-2 pt-2 border-t border-slate-200">
        <button
          type="button"
          disabled={isSubmitting}
          onClick={handleApprove}
          className="px-4 py-2 rounded bg-green-600 text-white text-sm font-medium disabled:opacity-50"
        >
          Onayla
        </button>
        {confirmingReject ? (
          <>
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => {
                setConfirmingReject(false);
                onReject();
              }}
              className="px-4 py-2 rounded bg-red-600 text-white text-sm font-medium disabled:opacity-50"
            >
              Reddi Onayla
            </button>
            <button
              type="button"
              onClick={() => setConfirmingReject(false)}
              className="px-4 py-2 rounded border border-slate-300 text-sm text-slate-600"
            >
              Vazgeç
            </button>
          </>
        ) : (
          <button
            type="button"
            disabled={isSubmitting}
            onClick={() => setConfirmingReject(true)}
            className="px-4 py-2 rounded border border-red-300 text-red-700 text-sm font-medium disabled:opacity-50"
          >
            Reddet
          </button>
        )}
      </div>
    </div>
  );
}
