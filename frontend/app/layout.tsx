import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TrustBoard",
  description:
    "The weekly trust league for data teams. Scores computed from DataHub and written back to the graph.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
