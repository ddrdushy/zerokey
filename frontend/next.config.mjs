/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // Per VISUAL_IDENTITY.md: EN, BM, ZH, TA are all first-class.
  i18n: undefined, // App Router uses route-segment based i18n; wired in Phase 1+.
};

export default nextConfig;
