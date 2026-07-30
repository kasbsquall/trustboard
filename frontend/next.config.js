/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    // 127.0.0.1, not localhost: Node resolves localhost to ::1 first and uvicorn
    // binds IPv4 only, so the default failed on a machine where the API was
    // running fine. See the matching note in lib/api.ts.
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000",
  },
};

module.exports = nextConfig;
