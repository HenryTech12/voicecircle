/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Atkinson Hyperlegible"', "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        display: ['"Fraunces"', "Georgia", "serif"],
      },
      colors: {
        bg: "#F6F4EE",
        surface: "#FFFFFF",
        line: "#DCD7CC",
        ink: "#1F1D18",
        muted: "#5E5B53",
        brand: { DEFAULT: "#0E5C61", dark: "#0A4447", soft: "#E1EEEE" },
        good: { DEFAULT: "#2F6B1F", soft: "#E5F0DE" },
        bad: { DEFAULT: "#A3262A", soft: "#F8E3E2" },
        warn: { DEFAULT: "#8A4B0F", soft: "#F7EAD9" },
      },
      borderRadius: { xl2: "1.25rem" },
    },
  },
  plugins: [],
};
