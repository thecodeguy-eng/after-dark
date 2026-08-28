from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseRedirect
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views.generic import ListView, DetailView
from .models import Movie, Category, Tag, Series, Episode
from .utils import resolve_xvideos_direct_urls, find_xvideos_embed_url
import json
from django.template.loader import render_to_string

def load_more_movies(request):
    """API endpoint for loading more movies via AJAX"""
    page = request.GET.get('page', 1)
    
    try:
        page = int(page)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid page number'}, status=400)
    
    # Get published movies with same ordering as home view
    movies_queryset = Movie.objects.filter(status='publish').select_related().prefetch_related('categories', 'tags')
    
    paginator = Paginator(movies_queryset, 12)  # Load 12 movies per request
    
    try:
        page_obj = paginator.page(page)
    except:
        return JsonResponse({
            'movies_html': '',
            'has_next': False,
            'current_page': page,
            'total_pages': 0,
            'count': 0,
            'message': 'No more movies available'
        })
    
    # Render movies as HTML using a partial template
    movies_html = render_to_string('movies/partials/movie_cards.html', {
        'movies': page_obj.object_list,
        'request': request
    })
    
    return JsonResponse({
        'movies_html': movies_html,
        'has_next': page_obj.has_next(),
        'current_page': page,
        'total_pages': paginator.num_pages,
        'count': len(page_obj.object_list)
    })

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

def download_movie(request, movie_id):
    """Resolve a direct, downloadable video URL and redirect to it.

    xvideos signs its direct mp4 URLs with a short-lived expiry token, so
    they're resolved live here (rather than at scrape time) to guarantee
    a working link.
    """
    movie = get_object_or_404(Movie, id=movie_id)

    embed_url = find_xvideos_embed_url(movie)
    if not embed_url:
        return JsonResponse({'error': 'No resolvable video source for this movie'}, status=404)

    try:
        direct_urls = resolve_xvideos_direct_urls(embed_url)
    except Exception as e:
        return JsonResponse({'error': f'Failed to resolve download link: {e}'}, status=502)

    download_url = direct_urls.get('high') or direct_urls.get('low')
    if not download_url:
        return JsonResponse({'error': 'Could not find a direct video URL'}, status=502)

    return HttpResponseRedirect(download_url)


def resolve_video_source(request, movie_id):
    """Resolve a movie's playable direct mp4 URL as JSON, for the player to
    fetch client-side. Playing the raw file directly (instead of embedding
    xvideos' own player page in an iframe) skips xvideos' own pre-roll ads,
    since those are injected by their player page, not the video file itself.
    """
    movie = get_object_or_404(Movie, id=movie_id)

    embed_url = find_xvideos_embed_url(movie)
    if not embed_url:
        return JsonResponse({'error': 'No resolvable video source for this movie'}, status=404)

    try:
        direct_urls = resolve_xvideos_direct_urls(embed_url)
    except Exception as e:
        return JsonResponse({'error': f'Failed to resolve video: {e}'}, status=502)

    play_url = direct_urls.get('high') or direct_urls.get('low')
    if not play_url:
        return JsonResponse({'error': 'Could not find a direct video URL'}, status=502)

    return JsonResponse({'url': play_url})

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