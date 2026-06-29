@echo off
:: Deploy automatico para Vercel
:: Executa da RAIZ do repo (onde fica .vercel/project.json)
:: O Vercel usa rootDirectory: "admin" do projeto, fazendo upload apenas de admin/

set REPO_ROOT=C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Área de Trabalho\Projeto Automatização Dashboard
cd /d "%REPO_ROOT%"

echo.
echo Gerando snapshots...
node admin\scripts\generate-snapshots.mjs

echo.
echo Fazendo deploy Vercel (aguarde ~60s)...
vercel deploy --prod --yes

echo.
echo Reiniciando PM2 local (sincroniza com Vercel)...
pm2 restart dashboard-admin
if errorlevel 1 pm2 start "%REPO_ROOT%\admin\ecosystem.config.js"

echo.
echo Concluido! https://sindicompany-dashboards.vercel.app
