import js from "@eslint/js";
import ts from "typescript-eslint";

export default ts.config(
  { ignores: ["dist/**", "src-tauri/**", "src/api/schema.d.ts", "test-results/**"] },
  js.configs.recommended,
  ...ts.configs.recommended,
  { files: ["e2e/**/*.ts"], languageOptions: { globals: { process: "readonly" } } },
  { files: ["**/*.{ts,tsx}"], rules: { "@typescript-eslint/no-unused-vars": ["error", { "argsIgnorePattern": "^_" }] } },
);
