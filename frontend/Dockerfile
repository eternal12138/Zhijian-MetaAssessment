FROM node:22-alpine AS build

RUN corepack enable
WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

# Uploaded ZIPs may have been extracted under umask 077. Vite preserves the
# permissions of public assets: root-only fonts/images would return HTTP 403
# from Nginx workers. Normalize ONLY public web files in the final image.
RUN find /usr/share/nginx/html -type d -exec chmod 755 {} + \
    && find /usr/share/nginx/html -type f -exec chmod 644 {} +

EXPOSE 80
