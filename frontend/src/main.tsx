import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ExtractionProvider } from './contexts/ExtractionContext';
import App from './App';
import SafetyPage from './pages/SafetyPage';
import HistoryPage from './pages/HistoryPage';
import './globals.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ExtractionProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<App />} />
          <Route path="/safety" element={<SafetyPage />} />
          <Route path="/history" element={<HistoryPage />} />
        </Routes>
      </BrowserRouter>
    </ExtractionProvider>
  </React.StrictMode>,
);
