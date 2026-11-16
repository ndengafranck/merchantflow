import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage", "test-results", "playwright-report"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  reactHooks.configs.flat.recommended,
  {
    languageOptions: { globals: { ...globals.browser } },
    rules: {
      // The session is the only place allowed to hold credentials, and it
      // lives in an HttpOnly cookie. Keep web storage out of the codebase.
      "no-restricted-globals": [
        "error",
        { name: "localStorage", message: "Do not persist data in localStorage." },
        { name: "sessionStorage", message: "Do not persist data in sessionStorage." },
      ],
    },
  },
  {
    // The browser tests read web storage only to assert that it is empty.
    files: ["e2e/**"],
    rules: { "no-restricted-globals": "off" },
  },
);
