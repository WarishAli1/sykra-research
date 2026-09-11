import type { NextConfig } from "next";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  reactCompiler: false,
  output: 'standalone',
  outputFileTracingRoot: path.join(frontendRoot),
};

export default nextConfig;
