# movies/urls.py
from django.urls import path
from . import views

app_name = 'movies'

urlpatterns = [
    path('ping/', views.ping_view, name='ping'),

    path('', views.HomeView.as_view(), name='home'),
    path('api/load-more/', views.load_more_movies, name='load_more_movies'),
    path('search/', views.search_view, name='search'),
    path('categories/', views.AllCategoriesView.as_view(), name='all_categories'),
    path('series/', views.AllSeriesView.as_view(), name='all_series'),
    path('category/<slug:slug>/', views.CategoryView.as_view(), name='category'),
    path('series/<slug:slug>/', views.SeriesView.as_view(), name='series_detail'),
    path('watch/<slug:slug>/', views.MovieDetailView.as_view(), name='movie_detail'),
    
    # API endpoints
    path('api/search/', views.api_search, name='api_search'),
    path('api/video/<int:movie_id>/', views.get_video_data, name='get_video_data'),
    path('api/download/<int:movie_id>/', views.download_movie, name='download_movie'),
    path('api/resolve/<int:movie_id>/', views.resolve_video_source, name='resolve_video_source'),
    path('thumb/<int:movie_id>/', views.movie_thumbnail_view, name='movie_thumbnail'),
]