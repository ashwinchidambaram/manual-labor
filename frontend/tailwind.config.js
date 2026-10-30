/** @type {import('tailwindcss').Config} */
// Semantic tokens only (DESIGN.md): every colour maps to a CSS custom property in src/index.css.
const v = (name) => `var(--${name})`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    // in ascending order, so a wider breakpoint always wins: `wide` is where the step rail docks on the left
    screens: {
      sm: "640px",
      md: "768px",
      lg: "1024px",
      wide: "1100px",
      xl: "1280px",
      roomy: "1400px",
      "2xl": "1536px",
    },
    extend: {
      colors: {
        paper: v("paper"),
        raised: v("raised"),
        rail: v("rail"),
        sunk: v("sunk"),
        line: { DEFAULT: v("line"), soft: v("line-soft"), strong: v("line-strong") },
        ink: v("ink"),
        muted: v("muted"),
        page: v("page"),
        act: { DEFAULT: v("act"), hover: v("act-hover"), on: v("on-act"), wash: v("act-wash"), line: v("act-line"), ink: v("act-ink") },
        needs: { wash: v("needs-wash"), fill: v("needs-fill"), line: v("needs-line"), ink: v("needs-ink") },
        done: { wash: v("done-wash"), mid: v("done-mid"), ink: v("done-ink") },
        fail: { DEFAULT: v("fail"), wash: v("fail-wash"), line: v("fail-line") },
        focus: v("focus"),
      },
      fontFamily: {
        read: ['"Atkinson Hyperlegible"', "ui-sans-serif", "system-ui", "sans-serif"],
      },
      // a 1.2 scale for the app's own words, 15px base (the manual's text is set larger, in `font-read`)
      fontSize: {
        "2xs": ["0.75rem", { lineHeight: "1.1rem" }],
        xs: ["0.8125rem", { lineHeight: "1.2rem" }],
        sm: ["0.875rem", { lineHeight: "1.3rem" }],
        base: ["0.9375rem", { lineHeight: "1.45rem" }],
        lg: ["1.125rem", { lineHeight: "1.55rem" }],
        xl: ["1.375rem", { lineHeight: "1.8rem" }],
        "2xl": ["1.625rem", { lineHeight: "2.05rem" }],
        read: ["1.0625rem", { lineHeight: "1.7rem" }],
      },
      transitionTimingFunction: {
        "out-quart": "cubic-bezier(0.25, 1, 0.5, 1)",
      },
      boxShadow: {
        lift: "0 1px 2px oklch(0.3 0.02 60 / 0.08), 0 8px 24px -16px oklch(0.3 0.03 60 / 0.35)",
        key: "0 1px 0 var(--line)",
      },
    },
  },
  plugins: [
    // A short window (a laptop at 200% zoom is about 720x450): Verify keeps the page strip and the text on screen
    // together by folding the status block, the open queue card and the step sheet to one line each.
    ({ addVariant }) => {
      addVariant("short", "@media (max-height: 600px)");
      addVariant("short-narrow", "@media (max-height: 600px) and (max-width: 1099.98px)");
    },
  ],
};
