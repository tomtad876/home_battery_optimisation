/** @type {import('tailwindcss').Config} */
// Design tokens — see brain vault `projects/business/battery-optimisation-design.md`.
// Colour is a code, not decoration:
//   chrome is monochrome (ink / neutrals), colour belongs to data + one accent.
// `signal` (lime) means charging and the brand, nothing else.
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx}',
    './pages/**/*.{js,ts,jsx,tsx}',
    './components/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // ---- surfaces & ink (dark-first "Control Room") ----
        canvas: '#0B0F17',
        surface: { DEFAULT: '#121826', 2: '#171E2A' },
        hairline: '#202938',
        ink: { DEFAULT: '#E7ECF5', muted: '#8B95A7', faint: '#5A6376' },

        // ---- data colours (one meaning each, same everywhere) ----
        signal: '#C3F53C',      // brand + battery charging
        solar: '#FFA51F',       // solar generation
        load: '#64748B',        // household demand (context → neutral)
        gridin: '#F87171',      // importing from the grid
        gridout: '#34D399',     // exporting to the grid
        discharge: '#A78BFA',   // battery discharging

        // ---- status (tuned for a dark canvas) ----
        danger: {
          DEFAULT: '#F87171',
          surface: 'rgba(248,113,113,0.10)',
          border: 'rgba(248,113,113,0.32)',
          ink: '#FCA5A5',
        },
        warn: {
          DEFAULT: '#F0B429',
          surface: 'rgba(240,180,41,0.10)',
          border: 'rgba(240,180,41,0.32)',
          ink: '#FCD34D',
        },
        ok: {
          DEFAULT: '#34D399',
          surface: 'rgba(52,211,153,0.10)',
          border: 'rgba(52,211,153,0.32)',
          ink: '#6EE7B7',
        },
      },
      borderRadius: { card: '14px' },
      boxShadow: {
        card: '0 1px 2px rgba(0,0,0,0.35), 0 12px 32px rgba(0,0,0,0.35)',
      },
    },
  },
  plugins: [],
}
