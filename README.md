## Requirements
- Python 3.8.10
- Django 4.2
- Django REST Framework

## Installation
After you cloned the repository, you want to create a virtual environment, so you have a clean python installation.
You can do this by running the command
```
python -m venv env
```

After this, it is necessary to activate the virtual environment, you can get more information about this [here](https://docs.python.org/3/tutorial/venv.html)

You can install all the required dependencies by running
```
pip install -r requirements.txt
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

## Create users and Tokens

First we need to create a user, so we can log in
```
http POST http://127.0.0.1:8000/api/v1/auth/register/ email="email@email.com" username="USERNAME" password1="PASSWORD" password2="PASSWORD"
```

After we create an account we can use those credentials to get a token

To get a token first we need to request
```
http http://127.0.0.1:8000/api/v1/auth/token/ username="username" password="password"
```
after that, we get the token
```
{
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIsImV4cCI6MTYxNjI5MjMyMSwianRpIjoiNGNkODA3YTlkMmMxNDA2NWFhMzNhYzMxOTgyMzhkZTgiLCJ1c2VyX2lkIjozfQ.hP1wPOPvaPo2DYTC9M1AuOSogdRL_mGP30CHsbpf4zA",
    "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNjE2MjA2MjIxLCJqdGkiOiJjNTNlNThmYjE4N2Q0YWY2YTE5MGNiMzhlNjU5ZmI0NSIsInVzZXJfaWQiOjN9.Csz-SgXoItUbT3RgB3zXhjA2DAv77hpYjqlgEMNAHps"
}
```
We got two tokens, the access token will be used to authenticated all the requests we need to make, this access token will expire after some time.
We can use the refresh token to request a need access token.

requesting new access token
```
http http://127.0.0.1:8000/api/v1/auth/token/refresh/ refresh="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIsImV4cCI6MTYxNjI5MjMyMSwianRpIjoiNGNkODA3YTlkMmMxNDA2NWFhMzNhYzMxOTgyMzhkZTgiLCJ1c2VyX2lkIjozfQ.hP1wPOPvaPo2DYTC9M1AuOSogdRL_mGP30CHsbpf4zA"
```
and we will get a new access token
```
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

## Database diagram

![Database diagram](db_diagram.png)
