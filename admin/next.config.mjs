/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pula verificação de tipos no build (Vercel)
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },

  // Inclui arquivos externos no trace do bundle (Next.js 14.2+)
  // admin/ está 1 nível abaixo do root do projeto
  // Nota: no Vercel, config/ e docs/ são lidos via snapshots.json (gerado no build)
  experimental: {
    outputFileTracingIncludes: {
      '/**': ['../config/**', '../docs/**'],
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