import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'Menlo', 'monospace'],
      },
      colors: {
        bg: {
          base: '#09090B',
          surface: '#111115',
          card: '#18181B',
          hover: '#1E1E24',
          elevated: '#222229',
        },
        border: {
          DEFAULT: '#27272A',
          subtle: '#1E1E24',
          focus: '#3F3F46',
        },
        accent: {
          DEFAULT: '#6366F1',
          hover: '#818CF8',
          muted: 'rgba(99,102,241,0.12)',
          border: 'rgba(99,102,241,0.3)',
        },
        success: {
          DEFAULT: '#22C55E',
          muted: 'rgba(34,197,94,0.12)',
          border: 'rgba(34,197,94,0.3)',
        },
        warning: {
          DEFAULT: '#EAB308',
          muted: 'rgba(234,179,8,0.12)',
          border: 'rgba(234,179,8,0.3)',
        },
        danger: {
          DEFAULT: '#EF4444',
          muted: 'rgba(239,68,68,0.12)',
          border: 'rgba(239,68,68,0.3)',
        },
        text: {
          primary: '#FAFAFA',
          secondary: '#A1A1AA',
          muted: '#52525B',
          disabled: '#3F3F46',
        },
      },
      animation: {
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-up': 'slideUp 0.25s ease-out',
        'slide-in': 'slideIn 0.3s ease-out',
        'pulse-dot': 'pulseDot 2s ease-in-out infinite',
        'spin-slow': 'spin 2s linear infinite',
        'shimmer': 'shimmer 1.5s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: { from: { opacity: '0' }, to: { opacity: '1' } },
        slideUp: { from: { opacity: '0', transform: 'translateY(6px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        slideIn: { from: { opacity: '0', transform: 'translateX(-8px)' }, to: { opacity: '1', transform: 'translateX(0)' } },
        pulseDot: { '0%,100%': { opacity: '1', transform: 'scale(1)' }, '50%': { opacity: '0.6', transform: 'scale(0.85)' } },
        shimmer: { '0%': { backgroundPosition: '-200% 0' }, '100%': { backgroundPosition: '200% 0' } },
      },
      backgroundImage: {
        'shimmer-gradient': 'linear-gradient(90deg, transparent 25%, rgba(255,255,255,0.04) 50%, transparent 75%)',
        'card-gradient': 'linear-gradient(135deg, rgba(255,255,255,0.02) 0%, transparent 100%)',
        'accent-glow': 'radial-gradient(ellipse at 50% 0%, rgba(99,102,241,0.15) 0%, transparent 60%)',
      },
    },
  },
  plugins: [],
};

export default config;
