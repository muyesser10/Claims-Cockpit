interface ShortcutHelpProps {
  onClose: () => void;
}

const SHORTCUTS: { keys: string; description: string }[] = [
  { keys: "a", description: "Onayla — hızlı onay, formdaki düzenlemeler gönderilmez" },
  { keys: "r", description: "Reddet — ikinci 'r' ya da Enter reddi onaylar" },
  { keys: "Esc", description: "Reddi onaylama adımından vazgeç" },
  { keys: "?", description: "Bu yardımı göster / gizle" },
];

// Kısayol yardımı. Ayrı bir modal kütüphanesi yok; sabit konumlu bir katman ve
// tıklanabilir arka plan yeterli (projenin geri kalanı da düz Tailwind).
export default function ShortcutHelp({ onClose }: ShortcutHelpProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-4 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium text-slate-700">Klavye Kısayolları</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-slate-400 hover:text-slate-600"
            aria-label="Kapat"
          >
            ✕
          </button>
        </div>
        <ul className="space-y-2">
          {SHORTCUTS.map((shortcut) => (
            <li key={shortcut.keys} className="flex gap-3 text-sm text-slate-600">
              <kbd className="min-w-[2rem] rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 text-center font-mono text-xs">
                {shortcut.keys}
              </kbd>
              <span>{shortcut.description}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-slate-400">
          Kısayollar bir ihbar seçiliyken çalışır; form alanlarına yazarken devre dışıdır.
        </p>
      </div>
    </div>
  );
}
