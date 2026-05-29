const path = require('path');

module.exports = {
  apps: [
    /* ── Next.js Admin (porta 3500) ─────────────────────────────── */
    {
      name: 'sindicompany-admin',
      script: 'C:\\Program Files\\nodejs\\node_modules\\npm\\bin\\npm-cli.js',
      // Modo PRODUÇÃO: sem hot-reload, sem EBUSY do OneDrive
      // Após cada importação, PM2 reinicia automaticamente o servidor
      args: 'run start',
      cwd: path.resolve(__dirname),
      watch: false,
      autorestart: true,
      max_restarts: 10,
      env: {
        NODE_ENV: 'production',
        PATH: 'C:\\Program Files\\nodejs;' + process.env.PATH,
      },
      error_file: path.resolve(__dirname, '..', 'data', 'logs', 'admin-error.log'),
      out_file:   path.resolve(__dirname, '..', 'data', 'logs', 'admin-out.log'),
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },

    /* ── Cloudflare Tunnel (URL pública) ────────────────────────── */
    {
      name: 'sindicompany-tunnel',
      script: path.resolve(__dirname, '..', 'scripts', 'start-tunnel.js'),
      cwd: path.resolve(__dirname, '..'),
      watch: false,
      autorestart: true,
      max_restarts: 20,
      restart_delay: 5000,
      env: {
        PATH: 'C:\\Program Files\\nodejs;' + process.env.PATH,
        NODE_ENV: 'production',
      },
      error_file: path.resolve(__dirname, '..', 'data', 'logs', 'tunnel-error.log'),
      out_file:   path.resolve(__dirname, '..', 'data', 'logs', 'tunnel-out.log'),
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },
  ],
};
