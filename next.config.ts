import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  // The engines' published boards are read from disk at request time; bundle them
  // into the server functions when they exist (the preview branch commits them).
  outputFileTracingIncludes: {
    "/*": ["./modeling/data/published/*.json"],
    "/api/v1/games": ["./modeling/data/published/*.json"],
  },
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
