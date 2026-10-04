import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: "var(--color-bg)",
        surface: "var(--color-surface)",
        "surface-elevated": "var(--color-surface-elevated)",
        border: "var(--color-border)",
        "border-strong": "var(--color-border-strong)",
        primary: "var(--color-text-primary)",
        secondary: "var(--color-text-secondary)",
        muted: "var(--color-text-muted)",
        accent: "var(--color-accent)",
        "accent-foreground": "var(--color-accent-foreground)",
        "accent-soft": "var(--color-accent-soft)",
        success: "var(--color-success)",
        warning: "var(--color-warning)",
        danger: "var(--color-danger)",
      },
      fontFamily: {
        ui: "var(--font-ui)",
        mono: "var(--font-mono)",
      },
      borderRadius: {
        DEFAULT: "var(--radius)",
        sm: "calc(var(--radius) - 4px)",
        lg: "calc(var(--radius) + 4px)",
      },
      spacing: {
        unit: "var(--spacing-unit)",
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
    },
  },
  plugins: [],
} satisfies Config;