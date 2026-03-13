/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "assets.b365api.com", pathname: "/images/**" },
    ],
  },
  async rewrites() {
    const backend =
      process.env.BACKEND_URL ||
      (process.env.BACKEND_PORT
        ? `http://backend:${process.env.BACKEND_PORT}`
        : "http://backend:12000");
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
