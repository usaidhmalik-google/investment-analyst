import typography from '@tailwindcss/typography';

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        brand: {
          50: '#eef6ff',
          100: '#d9eaff',
          200: '#bcdaff',
          300: '#8ec2ff',
          400: '#599fff',
          500: '#3378fc',
          600: '#1d58f1',
          700: '#1543de',
          800: '#1837b4',
          900: '#1a338d',
          950: '#152156',
        },
      },
      keyframes: {
        flash: {
          '0%, 100%': { backgroundColor: 'transparent' },
          '30%': { backgroundColor: 'rgba(51, 120, 252, 0.25)' },
        },
      },
      animation: {
        flash: 'flash 1.6s ease-in-out',
      },
    },
  },
  plugins: [typography],
};
