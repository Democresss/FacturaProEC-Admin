import React, { useState, useCallback } from 'react';

type Variant = 'default' | 'primary' | 'success' | 'warning' | 'danger';

interface AsyncButtonProps {
  children: React.ReactNode;
  onClick: () => Promise<any> | any;
  variant?: Variant;
  size?: 'sm' | 'md';
  disabled?: boolean;
  confirmText?: string;
  confirmTitle?: string;
  runningText?: string;
  className?: string;
  style?: React.CSSProperties;
  icon?: React.ReactNode;
  title?: string;
}

/** Botón que ejecuta una acción async, se deshabilita mientras corre y muestra spinner. */
export function AsyncButton({
  children, onClick, variant = 'default', size = 'md',
  disabled = false, confirmText, confirmTitle = 'Confirmar',
  runningText, className = '', style, icon, title,
}: AsyncButtonProps) {
  const [running, setRunning] = useState(false);

  const handleClick = useCallback(async (e: React.MouseEvent) => {
    e.preventDefault();
    if (running || disabled) return;
    if (confirmText && !window.confirm(`${confirmTitle}\n\n${confirmText}`)) return;
    setRunning(true);
    try {
      await onClick();
    } catch (err) {
      console.error('[AsyncButton] error:', err);
    } finally {
      setRunning(false);
    }
  }, [running, disabled, confirmText, confirmTitle, onClick]);

  const cls = ['btn'];
  if (variant === 'primary') cls.push('btn-primary');
  else if (variant === 'success') cls.push('btn-success');
  else if (variant === 'warning') cls.push('btn-warning');
  else if (variant === 'danger') cls.push('btn-danger');
  if (size === 'sm') cls.push('btn-sm');
  if (className) cls.push(className);

  return (
    <button className={cls.join(' ')} disabled={running || disabled} onClick={handleClick} title={title} style={style}>
      {running ? <span className="spinner" /> : icon}
      <span>{running ? (runningText || 'Procesando…') : children}</span>
    </button>
  );
}
