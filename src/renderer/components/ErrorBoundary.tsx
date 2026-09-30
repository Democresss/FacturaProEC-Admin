import React from 'react';

/**
 * Si una parte de la pantalla falla, se muestra el error en esa parte y el resto de la app sigue.
 * Antes un error en cualquier componente dejaba toda la ventana en blanco.
 */
export class ErrorBoundary extends React.Component<{ children: React.ReactNode; nombre?: string; silencioso?: boolean },
                                                   { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(`[ErrorBoundary${this.props.nombre ? ' ' + this.props.nombre : ''}]`, error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    if (this.props.silencioso) return null;
    return (
      <div className="empty" style={{ padding: 24 }}>
        <div className="empty-icon">⚠</div>
        <div>Esta sección tuvo un error{this.props.nombre ? ` (${this.props.nombre})` : ''}.</div>
        <div className="muted fs-12 mt-8 mono">{String(this.state.error?.message || this.state.error)}</div>
        <button className="btn btn-primary mt-16" onClick={() => this.setState({ error: null })}>Reintentar</button>
      </div>
    );
  }
}
