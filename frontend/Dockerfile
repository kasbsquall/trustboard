# Frontend del dashboard TrustBoard (Next.js). Construir desde frontend/:
#   docker build -f frontend/Dockerfile -t trustboard-frontend ./frontend
# La URL publica del backend se pasa en build time (el cliente la necesita).
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# Limita el heap de Node para no agotar la RAM de un host compartido con otras apps.
ENV NODE_OPTIONS=--max-old-space-size=768
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.js ./next.config.js

EXPOSE 3000
CMD ["npm", "run", "start"]
