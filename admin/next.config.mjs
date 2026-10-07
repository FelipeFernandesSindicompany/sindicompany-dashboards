/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pula verificação de tipos no build (Vercel)
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },

  // Inclui config/ no trace do bundle para PM2 local e dev (condominios.json).
  // docs/ NÃO é incluído: no Vercel os HTMLs são servidos do GitHub Pages;
  // no PM2 local são lidos diretamente do filesystem (SINDICOMPANY_PM2).
  experimental: {
    outputFileTracingIncludes: {
      '/**': ['../config/**'],
    },
  },

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