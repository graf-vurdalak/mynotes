from django.urls import path

from . import views

app_name = "planner"

urlpatterns = [
    path("", views.scope_picker, name="home"),
    # Личный раздел
    path("personal/", views.personal_calendar, name="personal"),
    path("personal/feed/", views.personal_feed, name="feed"),
    path("personal/event/new/", views.event_create, name="event_create"),
    path("personal/event/<uuid:pk>/edit/", views.event_update, name="event_update"),
    path("personal/event/<uuid:pk>/delete/", views.event_delete, name="event_delete"),
    # Рабочий раздел
    path("work/", views.work_board, name="work"),
    path("work/task/new/", views.task_create, name="task_create"),
    path("work/task/<uuid:pk>/", views.task_detail, name="task"),
    path("work/task/<uuid:pk>/panel/", views.task_panel, name="task_panel"),
    path("work/task/<uuid:pk>/edit/", views.task_update, name="task_update"),
    path("work/task/<uuid:pk>/delete/", views.task_delete, name="task_delete"),
    path("work/task/<uuid:pk>/move/", views.task_move, name="task_move"),
    path("work/task/<uuid:pk>/comment/", views.comment_add, name="comment_add"),
    path("work/comment/<uuid:pk>/delete/", views.comment_delete, name="comment_delete"),
    path("work/statuses/", views.status_list, name="statuses"),
    path("work/statuses/new/", views.status_create, name="status_create"),
    path("work/statuses/<uuid:pk>/", views.status_update, name="status_update"),
    path("work/statuses/<uuid:pk>/delete/", views.status_delete, name="status_delete"),
    path("work/statuses/reorder/", views.status_reorder, name="status_reorder"),
    # Проекты и поиск
    path("projects/", views.project_list, name="projects"),
    path("projects/new/", views.project_create, name="project_create"),
    path("projects/<uuid:pk>/edit/", views.project_update, name="project_update"),
    path("projects/<uuid:pk>/delete/", views.project_delete, name="project_delete"),
    path("projects/<uuid:pk>/archive/", views.project_toggle_archive, name="project_archive"),
    path("search/", views.planner_search, name="search"),
]
