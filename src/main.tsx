import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import ErrorBoundary from './components/ErrorBoundary.tsx';
import './index.css';

const API_URL = import.meta.env.VITE_API_BASE_URL;

async function wakeBackend(): Promise<void> {
  if (!API_URL) {
    console.error('VITE_API_BASE_URL is not configured');
    return;
  }

  try {
    console.log('Waking backend...');

    const response = await fetch(`${API_URL}/health`, {
      method: 'GET',
      cache: 'no-store',
    });

    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`);
    }

    console.log('Backend is ready:', await response.json());
  } catch (error) {
    console.error('Backend wake-up failed:', error);
  }
}

async function startApp() {
  await wakeBackend();

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </StrictMode>,
  );
}

startApp();