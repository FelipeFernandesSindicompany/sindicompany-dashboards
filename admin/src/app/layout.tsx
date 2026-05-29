import type { Metadata, Viewport } from 'next';
import './globals.css';
import { Sidebar } from '@/components/layout/Sidebar';

export const metadata: Metadata = {
  title: 'Sindicompany Admin',
  description: 'Plataforma de gestão de dashboards financeiros',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>
        <Sidebar />
        {/*
          Desktop: ml-[220px] para não sobrepor o sidebar lateral
          Mobile:  ml-0, pt-14 (header fixo topo), pb-16 (bottom nav)
        */}
        <main className="md:ml-[220px] min-h-screen pt-14 md:pt-0 pb-16 md:pb-0">
          {children}
        </main>
      </body>
    </html>
  );
}
