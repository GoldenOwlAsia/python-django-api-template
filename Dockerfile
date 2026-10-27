# pull official base image
FROM python:3.12-alpine

# set work directory
WORKDIR /usr/src/app

# install python dependencies (dev, test or prod)
ARG REQUIREMENTS=dev
COPY ./requirements ./requirements
RUN pip install --no-cache-dir -r requirements/${REQUIREMENTS}.txt

# copy docker-entrypoint.sh
COPY ./docker-entrypoint.sh ./docker-entrypoint.sh

# copy project
COPY . .

RUN ["chmod", "+x", "./docker-entrypoint.sh"]
