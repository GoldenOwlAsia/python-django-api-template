# python-django-api-template

## Overview
The python-django-api-template serves as the boilerplate for constructing a Django project. :goat: :goat: :goat:
## Requirements
- Python 3.12.10
- Django 4.2
- Django REST Framework

## Install and run locally from a virtual environment
After cloning the repository, you'll want to create a virtual environment to ensure a clean Python installation.

You can achieve this by executing the following command.
```
python -m venv env
```

After this, it is necessary to activate the virtual environment, you can get more information about this [here](https://docs.python.org/3/tutorial/venv.html)

You can install all the required dependencies by running
```
pip install -r requirements/dev.txt
```

## Start and Use
Run migration
```
python manage.py makemigrations
python manage.py migrate
```
Run server.
```
python manage.py runserver
```
Run redis server.
```
redis-server
```
Run celery.
```
celery -A api worker -l INFO
```
## Create users and Tokens

First, we need to create a user so that we can log in.
```sh
curl --location --request POST 'http://127.0.0.1:8000/api/v1/auth/register/' \
--header 'Content-Type: application/json' \
--data-raw '{
    "email": "email@gmail.com",
    "username": "username",
    "password": "password"
}'
```

Once we have created an account, we can utilize those credentials to obtain a token.

First, we need to request a token.
```sh
curl --location --request POST 'http://127.0.0.1:8000/api/v1/auth/login/' \
--header 'Content-Type: application/json' \
--data-raw '{
    "username": "username",
    "password": "password"
}'
```
after that, we get the token
```sh
{
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIsImV4cCI6MTYxNjI5MjMyMSwianRpIjoiNGNkODA3YTlkMmMxNDA2NWFhMzNhYzMxOTgyMzhkZTgiLCJ1c2VyX2lkIjozfQ.hP1wPOPvaPo2DYTC9M1AuOSogdRL_mGP30CHsbpf4zA",
    "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNjE2MjA2MjIxLCJqdGkiOiJjNTNlNThmYjE4N2Q0YWY2YTE5MGNiMzhlNjU5ZmI0NSIsInVzZXJfaWQiOjN9.Csz-SgXoItUbT3RgB3zXhjA2DAv77hpYjqlgEMNAHps"
}
```
We have obtained two tokens: the access token will be used to authenticate all the requests we need to make, and this access token will expire after some time.

We can use the refresh token to request a new access token when needed.

requesting new access token by refresh token
```sh
curl --location --request POST 'http://127.0.0.1:8000/api/v1/auth/token/refresh/' \
--header 'Content-Type: application/json' \
--data-raw '{
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNjE2MjA2MjIxLCJqdGkiOiJjNTNlNThmYjE4N2Q0YWY2YTE5MGNiMzhlNjU5ZmI0NSIsInVzZXJfaWQiOjN9.Csz-SgXoItUbT3RgB3zXhjA2DAv77hpYjqlgEMNAHps"
}'
```
and we will get a new access token
```sh
{
    "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNjE2MjA4Mjk1LCJqdGkiOiI4NGNhZmMzMmFiZDA0MDQ2YjZhMzFhZjJjMmRiNjUyYyIsInVzZXJfaWQiOjJ9.NJrs-sXnghAwcMsIWyCvE2RuGcQ3Hiu5p3vBmLkHSvM"
}
```

## API document

Visit `http://127.0.0.1:8000/swagger/` to check API document.

## Run unitest

`python manage.py test`

## Load seed data

`python manage.py loaddata authentication/fixtures/customer.json --app authentication.customer`

## Run docker

`docker compose up`

## Database diagram

![Database diagram](db_diagram.png)
