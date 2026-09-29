import { Component, ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

interface ErrorBoundaryBase {
  state: ErrorBoundaryState;
  props: ErrorBoundaryProps;
  setState(patch: Partial<ErrorBoundaryState>): void;
  forceUpdate(): void;
  render(): ReactNode;
}

const ErrorBoundaryBase = Component as unknown as new (props: ErrorBoundaryProps) => ErrorBoundaryBase;

export class ErrorBoundary extends ErrorBoundaryBase {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: unknown) {
    console.error('[SafeMoveAI] uncaught render/effect error:', error, info);
  }

  private handleReload = () => {
    this.setState({ error: null });
    window.location.reload();
  };

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div
          id="app-error-boundary"
          style={{
            minHeight: '100vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
            background: '#0a0e14',
            color: '#f1f5f9',
            fontFamily: 'system-ui, -apple-system, sans-serif',
          }}
        >
          <div
            style={{
              maxWidth: '560px',
              width: '100%',
              background: '#111722',
              border: '1px solid #1f2937',
              borderRadius: '16px',
              padding: '28px',
              boxShadow: '0 10px 30px rgba(2,6,23,0.6)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <span
                style={{
                  width: '10px',
                  height: '10px',
                  borderRadius: '9999px',
                  background: '#dc2626',
                  display: 'inline-block',
                }}
              />
              <h1 style={{ fontSize: '18px', fontWeight: 700, margin: 0 }}>
                SafeMove AI hit an unexpected error
              </h1>
            </div>
            <p style={{ fontSize: '14px', color: '#94a3b8', margin: '0 0 14px' }}>
              An unexpected error occurred while rendering the application. Your data is safe —
              reload to continue.
            </p>
            <div
              style={{
                background: 'rgba(239,68,68,0.1)',
                border: '1px solid rgba(239,68,68,0.3)',
                borderRadius: '8px',
                padding: '10px 12px',
                fontSize: '12px',
                color: '#fca5a5',
                wordBreak: 'break-word',
                marginBottom: '16px',
              }}
            >
              {String(this.state.error.message || this.state.error)}
            </div>
            <div style={{ display: 'flex', gap: '10px' }}>
              <button
                type="button"
                onClick={this.handleReload}
                style={{
                  background: '#22c55e',
                  color: '#052e16',
                  border: 'none',
                  borderRadius: '8px',
                  padding: '8px 16px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Reload application
              </button>
              <button
                type="button"
                onClick={() => this.setState({ error: null })}
                style={{
                  background: '#1a2230',
                  color: '#f1f5f9',
                  border: '1px solid #1f2937',
                  borderRadius: '8px',
                  padding: '8px 16px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;