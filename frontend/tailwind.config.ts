import type { Config } from "tailwindcss";

const cssVar = (name: string) => `var(--${name})`;

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: cssVar("color-primary"),
        "primary-hover": cssVar("color-primary-hover"),
        "primary-light": cssVar("color-primary-light"),
        "primary-border": cssVar("color-primary-border"),
        teal: cssVar("color-teal"),
        "teal-hover": cssVar("color-teal-hover"),
        "teal-light": cssVar("color-teal-light"),
        "teal-border": cssVar("color-teal-border"),
        purple: cssVar("color-purple"),
        "purple-light": cssVar("color-purple-light"),
        "purple-border": cssVar("color-purple-border"),
        amber: cssVar("color-amber"),
        "amber-light": cssVar("color-amber-light"),
        "amber-border": cssVar("color-amber-border"),
        red: cssVar("color-red"),
        "red-light": cssVar("color-red-light"),
        surface: cssVar("color-surface"),
        page: cssVar("color-page"),
        text: cssVar("color-text"),
      },
      fontFamily: {
        sans: [cssVar("font-sans")],
        mono: [cssVar("font-mono")],
        display: [cssVar("font-serif-display")],
      },
      borderRadius: {
        lg: cssVar("radius-lg"),
        md: cssVar("radius-md"),
        sm: cssVar("radius-sm"),
        xs: cssVar("radius-xs"),
      },
      keyframes: {
        "radar-ping": {
          "0%": { transform: "scale(1)", opacity: "0.6" },
          "100%": { transform: "scale(2.8)", opacity: "0" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "radar-ping": "radar-ping 2s cubic-bezier(0, 0, 0.2, 1) infinite",
        "fade-in": "fade-in 0.3s ease-out",
      },
    },
  },
  plugins: [],
};

export default config;
