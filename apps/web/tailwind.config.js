/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{vue,ts}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#33d133",
          pale: "#eefbee",
        },
        surface: "#ffffff",
        ink: "#17221f",
        paper: "#f4f5f2",
        muted: "#687772",
        line: "#dce2dd",
        danger: "#a94832",
        coral: "#dd7c53",
      },
      fontFamily: {
        sans: ["Outfit", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      fontSize: {
        micro: "7px",
        fine: "8px",
        meta: "9px",
        caption: "10px",
        control: "11px",
        label: "12px",
        detail: "13px",
        body: "14px",
        copy: "15px",
        lead: "16px",
        "title-sm": "18px",
        title: "19px",
        "title-lg": "20px",
      },
      borderRadius: {
        control: "7px",
        action: "8px",
        nav: "9px",
        field: "10px",
        composer: "11px",
        panel: "12px",
      },
      screens: {
        tablet: { max: "1020px" },
        mobile: { max: "760px" },
        phone: { max: "500px" },
      },
      keyframes: {
        "knowledge-orbit": {
          from: { transform: "rotate(0deg) translateX(38px) rotate(0deg)" },
          to: {
            transform: "rotate(360deg) translateX(38px) rotate(-360deg)",
          },
        },
        "thinking-pulse": {
          "50%": { opacity: "0.3", transform: "scale(0.72)" },
        },
      },
      animation: {
        orbit: "knowledge-orbit 6s linear infinite",
        "spin-fast": "spin 0.8s linear infinite",
        thinking: "thinking-pulse 1.3s infinite",
      },
    },
  },
  plugins: [],
};
