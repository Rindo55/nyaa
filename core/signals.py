from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from core import models, tasks

@receiver(m2m_changed, sender=models.BatchBundle.episodes.through)
def post_add_batch_bundle(sender, instance, action, **kwargs):
    if action == "post_add" and instance.episodes.exists():
        tasks.handle_batch_bundle.apply_async((instance.id,), countdown=60)
