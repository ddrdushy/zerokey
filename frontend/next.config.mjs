/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // Per VISUAL_IDENTITY.md: EN, BM, ZH, TA are all first-class.
  i18n: undefined, // App Router uses route-segment based i18n; wired in Phase 1+.
  // Lint runs in CI (`npm run lint`) — keep it out of the production
  // build so a stale rule can't block a deploy.
  eslint: { ignoreDuringBuilds: true },
  // Typecheck runs in CI (`npm run typecheck`) — same reasoning.
  // Next's build-time `tsc` is stricter than the editor and rejects
  // valid runtime code over JSX prop variance; keep it out of the
  // production build path.
  typescript: { ignoreBuildErrors: true },
};

export default nextConfig;
