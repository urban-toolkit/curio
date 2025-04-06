FROM node
WORKDIR /app/frontend
COPY ./utk-workflow ./utk-workflow
COPY ./urban-workflows ./urban-workflows

WORKDIR /app/frontend/utk-workflow/src/utk-ts
RUN rm -rf node_modules dist build
RUN npm install
RUN npm run build

WORKDIR /app/frontend/urban-workflows
RUN rm -rf node_modules dist build
RUN npm install
RUN npm run build

EXPOSE 8080
CMD ["npm", "run", "start"]
