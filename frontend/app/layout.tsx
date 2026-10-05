import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "FieldNet Monitor",
  description: "Operator console for the FieldNet sensor network",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav>
          <span className="brand">FieldNet Monitor</span>
          <Link href="/fleet">Fleet</Link>
          <Link href="/sensors">Sensors</Link>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
