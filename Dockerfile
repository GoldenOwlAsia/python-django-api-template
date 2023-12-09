# pull official base image
FROM python:3.12-alpine

# set work directory
WORKDIR /usr/src/app

# install python dependencies
COPY ./requirements ./requirements
RUN pip install --no-cache-dir -r requirements/dev.txt

# copy docker-entrypoint.sh
COPY ./docker-entrypoint.sh ./docker-entrypoint.sh

# copy project
COPY . .

RUN ["chmod", "+x", "./docker-entrypoint.sh"]
