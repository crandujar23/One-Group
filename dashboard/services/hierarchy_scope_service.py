from __future__ import annotations

from collections import deque

from django.contrib.auth import get_user_model

from core.models import UserProfile

User = get_user_model()


def get_downline_user_ids(root_user: User) -> set[int]:
    if not root_user or not root_user.is_authenticated:
        return set()

    root_id = int(root_user.id)
    visible_ids: set[int] = {root_id}
    queue: deque[int] = deque([root_id])

    while queue:
        current_id = queue.popleft()
        children = list(UserProfile.objects.filter(manager_id=current_id).values_list("user_id", flat=True))
        for child_id in children:
            child_id = int(child_id)
            if child_id in visible_ids:
                continue
            visible_ids.add(child_id)
            queue.append(child_id)

    return visible_ids

