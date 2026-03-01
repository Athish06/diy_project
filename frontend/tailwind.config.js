/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        accent: 'var(--accent)',
        'accent-hover': 'var(--accent-hover)',
        'card-bg': 'var(--card-bg)',
        'card-border': 'var(--card-border)',
        'input-bg': 'var(--input-bg)',
        'input-border': 'var(--input-border)',
        muted: 'var(--muted)',
        overlay: 'var(--overlay)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
};
