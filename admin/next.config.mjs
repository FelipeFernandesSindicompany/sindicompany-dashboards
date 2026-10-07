/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },

  experimental: {
    // Impede que arquivos de uploads e docs (lidos só localmente) sejam
    // rastreados como dependências das serverless functions no Vercel.
    outputFileTracingExcludes: {
      '*': ['../data/**', '../docs/**', '../output/**'],
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