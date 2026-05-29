/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pula verificação de tipos no build (Vercel)
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },

  // Inclui arquivos externos no bundle do Vercel
  outputFileTracingIncludes: {
    '/**': ['../config/**', '../docs/**'],
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