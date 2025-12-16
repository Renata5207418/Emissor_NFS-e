import { useEffect, useMemo, useRef, useState } from "react";

const normalize = (s="") =>
  s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

export default function CTNAutocomplete({
  value,           // string ex.: "01.01.01"
  onChange,        // (code: string) => void
  options,         // [{ code, label, section }]
  placeholder="Busque por código ou descrição…",
  disabled=false
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [hoverIndex, setHoverIndex] = useState(-1);
  const rootRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    const onClick = (e) => {
      if (!rootRef.current?.contains(e.target)) setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, []);

  // label exibida no input quando há value
  const selectedLabel = useMemo(() => {
    if (!value) return "";
    const found = options?.find(o => o.code === value);
    return found?.label || value;
  }, [value, options]);

  const filtered = useMemo(() => {
    const q = normalize(query);
    if (!q) return options || [];

    // 1. Cria uma versão da busca contendo apenas dígitos
    const qDigits = query.replace(/\D/g, "");

    return (options || []).filter(o => {
      // Verificação original (para buscar por texto ou com pontos)
      const hay = normalize(`${o.code} ${o.label}`);
      const regularMatch = hay.includes(q);

      // 2. Verificação nova (apenas dígitos)
      const codeDigits = o.code.replace(/\D/g, "");
      const digitsMatch = qDigits.length > 0 && codeDigits.includes(qDigits);

      // 3. Retorna true se QUALQUER uma das verificações for positiva
      return regularMatch || digitsMatch;
    });
  }, [query, options]);

  // estrutura agrupada por section
  const grouped = useMemo(() => {
    const map = new Map();
    for (const o of filtered) {
      const key = o.section || "Outros";
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(o);
    }
    return Array.from(map.entries()); // [ [section, arr], ... ]
  }, [filtered]);

  const flatList = useMemo(() => filtered, [filtered]); // p/ index por teclado

  const selectItem = (o) => {
    onChange?.(o.code);
    setQuery("");
    setOpen(false);
    // mantém label “bonita” no input
    requestAnimationFrame(() => inputRef.current?.blur());
  };

  const onKeyDown = (e) => {
    if (!open && (e.key.length === 1 || e.key === "Backspace")) setOpen(true);

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setHoverIndex((i) => Math.min(flatList.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHoverIndex((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      if (open && hoverIndex >= 0 && flatList[hoverIndex]) {
        e.preventDefault();
        selectItem(flatList[hoverIndex]);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
      setHoverIndex(-1);
    }
  };

  return (
    <div ref={rootRef} style={{ position: "relative" }}>
      <input
        ref={inputRef}
        type="text"
        disabled={disabled}
        placeholder={placeholder}
        value={open ? query : (value ? selectedLabel : query)}
        onFocus={() => setOpen(true)}
        onChange={(e) => { setQuery(e.target.value); setHoverIndex(-1); }}
        onKeyDown={onKeyDown}
        aria-expanded={open}
        aria-autocomplete="list"
        autoComplete="off"
        style={{ width: "100%" }}
      />

      {open && (
        <div
          role="listbox"
          style={{
            position: "absolute", zIndex: 50, insetInline: 0, maxHeight: 320,
            overflow: "auto", background: "#fff", border: "1px solid #ddd",
            borderRadius: 8, marginTop: 4, boxShadow: "var(--shadow-2, 0 10px 30px rgba(0,0,0,.08))"
          }}
        >
          {grouped.length === 0 && (
            <div style={{ padding: 12, color: "#666" }}>Nenhum resultado…</div>
          )}

          {grouped.map(([section, arr]) => (
            <div key={section}>
              <div style={{
                position: "sticky", top: 0, background: "#f6f7f9",
                padding: "6px 10px", fontSize: 12, fontWeight: 600, color: "#444"
              }}>
                {section}
              </div>
              {arr.map((o, idxInGroup) => {
                const globalIndex = flatList.indexOf(o);
                const active = hoverIndex === globalIndex;
                return (
                  <div
                    key={o.code}
                    role="option"
                    aria-selected={value === o.code}
                    onMouseEnter={() => setHoverIndex(globalIndex)}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => selectItem(o)}
                    style={{
                      padding: "8px 10px",
                      cursor: "pointer",
                      background: active ? "rgba(0,0,0,0.06)" : "transparent",
                      fontFamily: "inherit",
                      whiteSpace: "normal",
                      lineHeight: 1.25
                    }}
                  >
                    <div style={{ fontWeight: 600 }}>{o.code}</div>
                    <div style={{ fontSize: 12, color: "#555" }}>
                      {o.label.replace(`${o.code} - `, "")}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
