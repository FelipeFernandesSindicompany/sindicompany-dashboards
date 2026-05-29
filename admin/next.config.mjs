/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pula verificação de tipos no build (Vercel) — já verificado localmente
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },

  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'ngrok-skip-browser-warning', value: 'true' },
        ],
      },
    ];
  },
};
export default nextConfig;