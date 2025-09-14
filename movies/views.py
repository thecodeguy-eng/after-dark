from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views.generic import ListView, DetailView
from .models import Movie, Category, Tag, Series, Episode
import json


def ping_view(request):
    return JsonResponse({"status": "OK"})


def custom_404_view(request, exception):
    """
    Custom 404 view that shows only specific categories
    """
    # context = {
    #     'categories': get_sidebar_categories(),
    # }
    
    return render(request, 'movies/404.html', status=404)

class HomeView(ListView):
    model = Movie
    template_name = 'movies/home.html'
    context_object_name = 'movies'
    paginate_by = 20

    def get_queryset(self):
        return Movie.objects.filter(status='publish').select_related().prefetch_related('categories', 'tags')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['featured_movies'] = Movie.objects.filter(
            status='publish', is_sticky=True
        ).select_related().prefetch_related('categories', 'tags')[:6]
        
        context['recent_movies'] = Movie.objects.filter(
            status='publish'
        ).select_related().prefetch_related('categories', 'tags')[:12]
        
        context['popular_movies'] = Movie.objects.filter(
            status='publish'
        ).order_by('-view_count').select_related().prefetch_related('categories', 'tags')[:8]
        
        context['categories'] = Category.objects.annotate(
            movie_count=Count('movie')
        ).order_by('-movie_count')[:10]
        
        return context

class MovieDetailView(DetailView):
    model = Movie
    template_name = 'movies/detail.html'
    context_object_name = 'movie'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_object(self, queryset=None):
        movie = super().get_object(queryset)
        movie.increment_view_count()
        return movie

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        movie = self.object
        
        # Get related movies by category
        context['related_movies'] = Movie.objects.filter(
            categories__in=movie.categories.all(),
            status='publish'
        ).exclude(id=movie.id).distinct()[:6]
        
        # Check if this movie is part of a series
        try:
            episode = Episode.objects.get(movie=movie)
            context['episode'] = episode
            context['series_episodes'] = Episode.objects.filter(
                series=episode.series
            ).select_related('movie').order_by('season_number', 'episode_number')
        except Episode.DoesNotExist:
            pass
            
        return context

class CategoryView(ListView):
    model = Movie
    template_name = 'movies/category.html'
    context_object_name = 'movies'
    paginate_by = 20

    def get_queryset(self):
        self.category = get_object_or_404(Category, slug=self.kwargs['slug'])
        return Movie.objects.filter(
            categories=self.category,
            status='publish'
        ).select_related().prefetch_related('categories', 'tags')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category'] = self.category
        return context

class SeriesView(ListView):
    model = Episode
    template_name = 'movies/series.html'
    context_object_name = 'episodes'
    paginate_by = 50

    def get_queryset(self):
        self.series = get_object_or_404(Series, slug=self.kwargs['slug'])
        return Episode.objects.filter(
            series=self.series
        ).select_related('movie').order_by('season_number', 'episode_number')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['series'] = self.series
        return context

def search_view(request):
    query = request.GET.get('q', '')
    movies = []
    
    if query:
        movies = Movie.objects.filter(
            Q(title__icontains=query) | 
            Q(content__icontains=query) |
            Q(categories__name__icontains=query) |
            Q(tags__name__icontains=query),
            status='publish'
        ).distinct().select_related().prefetch_related('categories', 'tags')
    
    paginator = Paginator(movies, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'movies': page_obj,
        'query': query,
        'total_results': movies.count() if query else 0
    }
    
    return render(request, 'movies/search.html', context)

@csrf_exempt
def api_search(request):
    """AJAX search API"""
    if request.method == 'GET':
        query = request.GET.get('q', '')
        if len(query) < 2:
            return JsonResponse({'results': []})
        
        movies = Movie.objects.filter(
            title__icontains=query,
            status='publish'
        ).select_related()[:10]
        
        results = []
        for movie in movies:
            results.append({
                'id': movie.id,
                'title': movie.title,
                'slug': movie.slug,
                'image_url': movie.image_url,
                'url': movie.get_absolute_url(),
            })
        
        return JsonResponse({'results': results})
    
    return JsonResponse({'error': 'Invalid request method'})

def get_video_data(request, movie_id):
    """API endpoint to get video sources for a movie"""
    movie = get_object_or_404(Movie, id=movie_id)
    
    data = {
        'video_sources': movie.video_sources,
        'download_links': movie.download_links,
        'title': movie.title,
    }
    
    return JsonResponse(data)

class AllCategoriesView(ListView):
    model = Category
    template_name = 'movies/all_categories.html'
    context_object_name = 'categories'

    def get_queryset(self):
        return Category.objects.annotate(
            movie_count=Count('movie')
        ).order_by('-movie_count')

class AllSeriesView(ListView):
    model = Series
    template_name = 'movies/all_series.html'
    context_object_name = 'series_list'
    paginate_by = 20

    def get_queryset(self):
        return Series.objects.annotate(
            episode_count=Count('episodes')
        ).order_by('-created_at')