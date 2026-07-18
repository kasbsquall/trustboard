import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TrustBoard · Data Trust League",
  description:
    "Weekly trust scores for every data team, computed from DataHub signals and written back to the graph.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
