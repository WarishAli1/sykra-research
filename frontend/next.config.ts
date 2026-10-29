import type { NextConfig } from "next";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  reactCompiler: false,
  output: "standalone",
  outputFileTracingRoot: path.join(frontendRoot),
  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.resolve.alias = {
        ...config.resolve.alias,
        "html-to-docx": "html-to-docx/dist/html-to-docx.umd.js",
      };
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        path: false,
        util: false,
        events: false,
        stream: false,
        crypto: false,
      };
    }
    return config;
  },
};

export default nextConfig;