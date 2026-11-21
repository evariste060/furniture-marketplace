import js from "@eslint/js";
import tseslint from "typescript-eslint";
import hooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y-x";
import { defineConfig, globalIgnores } from "eslint/config";

// jsx-a11y: the maintained fork eslint-plugin-jsx-a11y-x (same rules); the original package does
// not support ESLint 10.
export default defineConfig([
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts", "playwright-report/**", "test-results/**", "src/lib/api/schema.d.ts"]),
  js.configs.recommended,
  tseslint.configs.recommended,
  { files: ["**/*.{ts,tsx}"], plugins: { "react-hooks": hooks }, rules: hooks.configs.recommended.rules },
  { files: ["**/*.{jsx,tsx}"], ...jsxA11y.configs.strict },
  {
    // SearchInput (the header's search box) renders an <input>.
    files: ["**/*.{jsx,tsx}"],
    rules: { "jsx-a11y-x/label-has-associated-control": ["error", { controlComponents: ["SearchInput"], depth: 3 }] },
  },
  {
    // Node scripts (npm run i18n:review) and their tests.
    files: ["scripts/**/*.mjs"],
    languageOptions: { globals: { URL: "readonly", process: "readonly", console: "readonly" } },
  },
]);
