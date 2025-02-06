from django.urls import path
from . import views

urlpatterns = [
    path('', views.CreateWorkoutView.as_view(), name='create-workout'),
    path('list/', views.WorkoutListView.as_view(), name='workout-list'),
    path('<int:id>/', views.WorkoutView.as_view(), name='specific-workout'),
    path('recommendation/', views.WorkoutRecommendation.as_view(), name ='recommendation' )
]