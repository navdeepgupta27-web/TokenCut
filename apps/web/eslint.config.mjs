import coreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

/**
 * Next 16 removed `next lint`, so ESLint runs directly (`npm run lint`).
 *
 * eslint-config-next 16 exports native flat config, so it is spread straight
 * in — no FlatCompat. (FlatCompat actually throws a circular-structure error
 * against this version, which is the clue that the compat layer is no longer
 * the right approach.)
 */
const config = [
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts", "*.tsbuildinfo"] },
  ...coreWebVitals,
  ...nextTypescript,
  {
    rules: {
      // Surface dead code, but allow the leading-underscore convention for
      // deliberately unused parameters.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
];

export default config;
