FROM node:23-slim

# Installing curl to check health status
RUN apt-get update && apt-get install -y curl

WORKDIR /app/frontend
COPY ./utk-workflow ./utk-workflow
COPY ./urban-workflows ./urban-workflows

WORKDIR /app/frontend/utk-workflow/src/utk-ts
RUN rm -rf node_modules dist build && npm ci --prefer-offline --no-audit && npm run build

WORKDIR /app/frontend/urban-workflows
RUN rm -rf node_modules dist build && npm ci --prefer-offline --no-audit && npm run build

EXPOSE 8080
CMD ["npm", "run", "start"]
