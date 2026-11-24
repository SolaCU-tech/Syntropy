from celery import shared_task


@shared_task
def ping() -> str:
    """Smallest possible task, used to check the worker is wired up."""
    return "pong"
