FROM node:18-bullseye AS build

ARG VITE_BACKEND_URL=""
ENV VITE_BACKEND_URL=${VITE_BACKEND_URL}

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

RUN npm run build

FROM nginx:1.25-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
