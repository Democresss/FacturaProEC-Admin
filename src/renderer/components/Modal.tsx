import React, { useEffect, useCallback } from 'react';

export interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  maxWidth?: number;
}

export function Modal({ open, title, onClose, children, footer, maxWidth }: ModalProps) {
  const onKey = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
  }, [onClose]);

  useEffect(() => {
    if (open) window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onKey]);

  if (!open) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: maxWidth || 720 }}>
        <div className="modal-header">
          <div className="modal-title">{title}</div>
          <button className="btn btn-sm" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

/** Modal de confirmación simple (ok/cancel). */
export function ConfirmModal({
  open, title, message, confirmLabel = 'Confirmar', cancelLabel = 'Cancelar',
  danger = false, onConfirm, onCancel,
}: {
  open: boolean; title: string; message: React.ReactNode;
  confirmLabel?: string; cancelLabel?: string; danger?: boolean;
  onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <Modal open={open} title={title} onClose={onCancel} maxWidth={480}
      footer={
        <>
          <button className="btn" onClick={onCancel}>{cancelLabel}</button>
          <button className={danger ? 'btn btn-danger' : 'btn btn-primary'} onClick={onConfirm}>{confirmLabel}</button>
        </>
      }>
      <div style={{ whiteSpace: 'pre-wrap' }}>{message}</div>
    </Modal>
  );
}

/** Modal de info (sólo OK). */
export function InfoModal({
  open, title, message, okLabel = 'OK', onOk,
}: {
  open: boolean; title: string; message: React.ReactNode;
  okLabel?: string; onOk: () => void;
}) {
  return (
    <Modal open={open} title={title} onClose={onOk} maxWidth={640}
      footer={<button className="btn btn-primary" onClick={onOk}>{okLabel}</button>}>
      <div style={{ whiteSpace: 'pre-wrap' }}>{message}</div>
    </Modal>
  );
}
