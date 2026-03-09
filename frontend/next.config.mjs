/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const backend =
      process.env.BACKEND_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      "http://localhost:11001";
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
