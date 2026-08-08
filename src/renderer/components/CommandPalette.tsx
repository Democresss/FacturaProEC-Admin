import React, { useState, useEffect, useRef, useMemo } from 'react';

export interface CommandItem {
  id: string;
  label: string;
  desc?: string;
  icon?: React.ReactNode;
  run: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  items: CommandItem[];
}

/** Command Palette (Ctrl+K) estilo Linear/Notion. */
export function CommandPalette({ open, onClose, items }: CommandPaletteProps) {
  const [query, setQuery] = useState('');
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(i =>
      i.label.toLowerCase().includes(q) || (i.desc?.toLowerCase().includes(q) || false)
    );
  }, [items, query]);

  useEffect(() => {
    if (open) {
      setQuery('');
      setSel(0);
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open]);

  useEffect(() => { setSel(0); }, [query]);

  if (!open) return null;

  const run = (i?: CommandItem) => {
    if (!i) return;
    i.run();
    onClose();
  };

  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div className="palette" onClick={e => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="palette-input"
          placeholder="Buscar acción o ir a…"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setSel(s => Math.min(s + 1, filtered.length - 1)); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(s => Math.max(s - 1, 0)); }
            else if (e.key === 'Enter') { e.preventDefault(); run(filtered[sel]); }
            else if (e.key === 'Escape') { e.preventDefault(); onClose(); }
          }}
        />
        <div className="palette-list">
          {filtered.length === 0 && (
            <div className="empty" style={{ padding: '20px' }}>Sin resultados</div>
          )}
          {filtered.map((item, i) => (
            <div
              key={item.id}
              className={`palette-item ${i === sel ? 'selected' : ''}`}
              onMouseEnter={() => setSel(i)}
              onClick={() => run(item)}
            >
              <span className="pl-icon">{item.icon || '▸'}</span>
              <span className="pl-label">{item.label}</span>
              {item.desc && <span className="pl-desc">{item.desc}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
