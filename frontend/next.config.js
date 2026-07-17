/** @type {import('next').NextConfig} */
const path = require('path');

const backendApiUrl = process.env.BACKEND_API_URL || 'http://127.0.0.1:8102';

const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ['localhost', '127.0.0.1', 'frontend.topiceye.orb.local'],
  turbopack: {
    root: path.resolve(__dirname),
  },
  // macOS Docker bind mount 下 inotify 不穿透，强制 webpack 轮询以启用 HMR
  webpack: (config) => {
    config.watchOptions = {
      poll: 1000,
      aggregateTimeout: 300,
    };
    return config;
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${backendApiUrl}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
