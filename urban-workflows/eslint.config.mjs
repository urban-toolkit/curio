import globals from "globals";
import pluginJs from "@eslint/js";
import tseslint from "typescript-eslint";
import pluginReact from "eslint-plugin-react";

/** @type {import('eslint').Linter.Config[]} */
export default [
  { files: ["**/*.{js,mjs,cjs,ts,jsx,tsx}"] },
  pluginReact.configs.flat.recommended,
  {
    languageOptions: {
      ...pluginReact.configs.flat.recommended.languageOptions,
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
      globals: globals.browser,
    },
  },
  pluginJs.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      "no-unused-vars": "off",
      "@typescript-eslint/no-unused-vars": "off",
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/ban-ts-comment": "off",
      "react/prop-types": "off",
      "react/no-unescaped-entities": "off",
      "no-useless-escape": "off",
      "@typescript-eslint/no-require-imports": "off",
      "prefer-const": "off",
      "no-undef": "off",
      "no-empty": "off",
    },
  },
  {
    ignores: ["node_modules/*"],
  },
  {
    "settings": {
      "react": {
        "version": "detect",
      },
    },
  },
];
