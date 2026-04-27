// Tailwind config — semantic-over-literal token naming per VISUAL_IDENTITY.md.
// Hardcoded colour values in component code are not permitted; all values flow
// through the tokens defined here and in src/app/globals.css.

import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // Brand palette — see VISUAL_IDENTITY.md "Color system".
        ink: "#0A0E1A", // ZeroKey Ink — primary text, marketing dark surface
        paper: "#FAFAF7", // ZeroKey Paper — primary product surface
        signal: "#C7F284", // ZeroKey Signal — single accent, used sparingly
        glow: "#F5E1A8", // ZeroKey Glow — marketing only

        slate: {
          50: "#F4F4EE",
          100: "#E8E8E0",
          200: "#D1D1C5",
          400: "#8A8A7F",
          600: "#4A4A42",
          800: "#1F1F1A",
        },

        // Semantic — used only when their meaning is being communicated.
        success: "#3FA568",
        warning: "#E8A93A",
        error: "#D4533F",
        info: "#4A6FB0",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Geist", "Inter", "ui-sans-serif", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      fontSize: {
        // 1.25 modular scale anchored at 16px (VISUAL_IDENTITY.md "Type scale").
        "2xs": ["12px", { lineHeight: "1.5" }],
        xs: ["14px", { lineHeight: "1.5" }],
        base: ["16px", { lineHeight: "1.5" }],
        lg: ["18px", { lineHeight: "1.5" }],
        xl: ["20px", { lineHeight: "1.4" }],
        "2xl": ["24px", { lineHeight: "1.4" }],
        "3xl": ["30px", { lineHeight: "1.3" }],
        "4xl": ["36px", { lineHeight: "1.3" }],
        "5xl": ["48px", { lineHeight: "1.2" }],
        "6xl": ["60px", { lineHeight: "1.2" }],
      },
      spacing: {
        // 8px baseline grid; explicit subset to discourage off-grid values.
        1: "4px",
        2: "8px",
        3: "12px",
        4: "16px",
        6: "24px",
        8: "32px",
        12: "48px",
        16: "64px",
      },
      borderRadius: {
        sm: "4px",
        DEFAULT: "8px",
        md: "10px",
        lg: "14px",
        xl: "20px",
      },
      transitionTimingFunction: {
        // Custom ease per VISUAL_IDENTITY.md "Motion".
        zk: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
      transitionDuration: {
        // Acknowledgments / panels / contextual changes — never exceed 500ms.
        ack: "120ms",
        panel: "220ms",
        ctx: "340ms",
      },
    },
  },
  plugins: [],
};

export default config;
