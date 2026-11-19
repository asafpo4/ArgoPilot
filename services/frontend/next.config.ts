import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pages render per request: no caching of service data.
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
