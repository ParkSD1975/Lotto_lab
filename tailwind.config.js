/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: [
    "./*.html",
    "./components/**/*.html",
    "./js/**/*.js",
    "./md/**/*.md"
  ],
  theme: {
    extend: {
      colors: {
        'primary': '#1d4ed8',
        'primary-dark': '#1e3a8a',
        'primary-ai': '#7c3aed',
        'primary-ai-dark': '#4c1d95',
        "active-green": "#E6FFED",
        "active-text": "#16A34A",
        "lotto-blue": "#3B82F6",
        "lotto-orange": "#F97316",
        "lotto-pink": "#EC4899",
        "lotto-purple": "#8B5CF6"
      },
      fontFamily: {
        "sans": ["Pretendard", "Inter", "sans-serif"],
        "pretendard": ["Pretendard", "Inter", "sans-serif"],
      },
    },
  },
  // [강제 주입] 빌드가 파일들을 못 찾는 경우를 대비하여 
  // GNB 메뉴에서 반드시 사용하는 핵심 클래스들을 명시적으로 포함
  safelist: [
    'fixed', 'top-0', 'inset-x-0', 'z-[100]', 'h-16', 'bg-white', 'border-b', 'border-slate-100',
    'flex', 'items-center', 'justify-between', 'px-6', 'lg:px-10', 'gap-3', 'group', 'flex-shrink-0',
    'bg-gradient-to-br', 'rounded-xl', 'shadow-lg', 'font-black', 'tracking-tight', 'text-slate-900',
    'overflow-x-auto', 'no-scrollbar', 'rounded-full', 'hover:bg-blue-50', 'transition-all',
    'absolute', 'right-0', 'top-[calc(100%+8px)]', 'w-[320px]', 'shadow-2xl', 'opacity-0', 'scale-95'
  ],
  plugins: [
    require('@tailwindcss/forms'),
    require('@tailwindcss/container-queries'),
  ],
}
