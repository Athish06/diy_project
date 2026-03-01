import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from './contexts/ThemeContext';
import { ExtractionProvider } from './contexts/ExtractionContext';
import App from './App';
import SafetyPage from './pages/SafetyPage';
import './globals.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <ExtractionProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<App />} />
            <Route path="/safety" element={<SafetyPage />} />
          </Routes>
        </BrowserRouter>
      </ExtractionProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
