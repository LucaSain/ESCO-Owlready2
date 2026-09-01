import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a plain HTML/CSS/JS bundle into ./out -- no Node server at runtime.
  // Required for Cloudflare Pages, which serves static assets.
  output: "export",

  // Cloudflare Pages serves /about as /about/index.html. Without this, Next
  // emits /about.html and deep links can 404 depending on the host's
  // fallback behaviour.
  trailingSlash: true,

  images: {
    // The default image loader needs a server. We use no next/image today,
    // but this keeps `next build` from failing the moment someone adds one.
    unoptimized: true,
  },
};

export default nextConfig;
