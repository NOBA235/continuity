/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The dashboard talks to the FastAPI backend over plain fetch() calls
  // (see lib/api.ts) rather than Next.js API routes, so it can be deployed
  // independently of the backend (e.g. Vercel + Cloud Run).
};

export default nextConfig;
