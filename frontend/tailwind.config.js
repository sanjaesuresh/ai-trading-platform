/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      // Warm-dark research theme. Surfaces are warm-tinted near-blacks (stone
      // family, not flat zinc) so the UI reads as serious-but-welcoming. Teal is
      // the single interactive accent (links, active nav, focus, primary
      // actions, the equity line); amber means highlight/caution only; emerald
      // and rose keep their up/down meaning. Standard Tailwind palettes are
      // still available — these are additive semantic tokens. Hex values let
      // opacity modifiers (e.g. bg-surface/60) keep working.
      colors: {
        canvas: '#15120f', // page background (warm near-black)
        surface: '#1d1a16', // cards
        raised: '#272320', // raised / hover surface
        hairline: '#322d28', // subtle borders
        edge: '#433c34', // stronger borders / input outlines
        ink: '#f6f4f1', // primary text
        'ink-muted': '#a8a29e', // secondary text
        'ink-subtle': '#9c948b', // labels / hints (WCAG AA on every surface)
        accent: '#2dd4bf', // teal — interactive
        'accent-bright': '#5eead4', // teal hover / emphasis
        'accent-dim': '#134e4a', // teal soft backgrounds
        caution: '#fbbf24', // amber — highlight / caution
        positive: '#34d399', // emerald — gains
        negative: '#fb7185', // rose — losses
      },
      borderRadius: {
        DEFAULT: '0.5rem',
        lg: '0.75rem',
        xl: '1rem',
      },
      boxShadow: {
        card: '0 1px 2px rgb(0 0 0 / 0.30), 0 1px 1px rgb(0 0 0 / 0.20)',
        raised: '0 4px 16px rgb(0 0 0 / 0.35)',
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono',
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Consolas',
          'monospace',
        ],
      },
    },
  },
  plugins: [],
}
