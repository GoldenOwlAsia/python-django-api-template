from api.celery import Celery

app = Celery('tasks',)

@app.task(name='run_every_monday_morning')
def add(x, y):
    return x + y
