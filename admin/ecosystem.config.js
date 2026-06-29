module.exports = {
  apps: [{
    name: 'dashboard-admin',
    script: 'node_modules/next/dist/bin/next',
    args: 'start -p 3500 -H 0.0.0.0',
    cwd: 'C:\\Users\\MF PRINTER\\OneDrive - Perfil de E-mail\\Área de Trabalho\\Projeto Automatização Dashboard\\admin',
    interpreter: 'node',
    env: {
      SINDICOMPANY_PM2: '1'
    }
  }]
}
