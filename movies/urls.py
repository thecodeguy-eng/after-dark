# movies/urls.py
from django.urls import path
from . import views

app_name = 'movies'

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('search/', views.search_view, name='search'),
    path('categories/', views.AllCategoriesView.as_view(), name='all_categories'),
    path('series/', views.AllSeriesView.as_view(), name='all_series'),
    path('category/<slug:slug>/', views.CategoryView.as_view(), name='category'),
    path('series/<slug:slug>/', views.SeriesView.as_view(), name='series_detail'),
    path('watch/<slug:slug>/', views.MovieDetailView.as_view(), name='movie_detail'),
    
    # API endpoints
    path('api/search/', views.api_search, name='api_search'),
    path('api/video/<int:movie_id>/', views.get_video_data, name='get_video_data'),
]