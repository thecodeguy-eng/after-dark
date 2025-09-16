from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import Movie, Category, Tag, Series, Episode
import json

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'movie_count', 'created_at']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']
    readonly_fields = ['created_at']
    
    def movie_count(self, obj):
        return obj.movie_set.count()
    movie_count.short_description = 'Movies'

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'movie_count', 'created_at']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']
    readonly_fields = ['created_at']
    
    def movie_count(self, obj):
        return obj.movie_set.count()
    movie_count.short_description = 'Movies'

@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = [
        'title_display', 
        'status', 
        'view_count', 
        'date', 
        'category_list', 
        'has_video', 
        'has_downloads',
        'scraped'
    ]
    list_filter = [
        'status', 
        'scraped', 
        'date', 
        'categories', 
        'tags'
    ]
    search_fields = ['title', 'content', 'excerpt']
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ['categories', 'tags']
    readonly_fields = [
        'wp_id', 
        'view_count', 
        'created_at', 
        'updated_at',
        'video_sources_display',
        'download_links_display'
    ]
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'title', 
                'slug', 
                'wp_id',
                'status', 
                'excerpt', 
                'content'
            )
        }),
        ('Media', {
            'fields': (
                'featured_media_id',
                'image_url',
                'video_sources',
                'video_sources_display',
                'download_links',
                'download_links_display'
            )
        }),
        ('Dates', {
            'fields': (
                'date', 
                'date_gmt', 
                'modified', 
                'modified_gmt'
            )
        }),
        ('Classification', {
            'fields': (
                'categories', 
                'tags'
            )
        }),
        ('Meta', {
            'fields': (
                'author_id',
                'comment_status',
                'ping_status',
                'is_sticky',
                'view_count',
                'meta_description',
                'canonical_url',
                'scraped',
                'created_at',
                'updated_at'
            )
        })
    )
    
    def title_display(self, obj):
        return format_html(
            '<a href="{}" target="_blank"><strong>{}</strong></a>',
            obj.get_absolute_url(),
            obj.title[:50] + '...' if len(obj.title) > 50 else obj.title
        )
    title_display.short_description = 'Title'
    
    def category_list(self, obj):
        categories = obj.categories.all()[:3]
        if categories:
            return ', '.join([cat.name for cat in categories])
        return '-'
    category_list.short_description = 'Categories'
    
    def has_video(self, obj):
        if obj.video_sources:
            return format_html(
                '<span style="color: green;">✓ {} source(s)</span>',
                len(obj.video_sources)
            )
        return format_html('<span style="color: red;">✗</span>')
    has_video.short_description = 'Video'
    
    def has_downloads(self, obj):
        if obj.download_links:
            return format_html(
                '<span style="color: green;">✓ {} link(s)</span>',
                len(obj.download_links)
            )
        return format_html('<span style="color: red;">✗</span>')
    has_downloads.short_description = 'Downloads'
    
    def video_sources_display(self, obj):
        if obj.video_sources:
            html = '<ul>'
            for i, source in enumerate(obj.video_sources, 1):
                label = source.get('label', f'Source {i}')
                url = source.get('url', 'No URL')
                source_type = source.get('type', 'Unknown')
                html += f'<li><strong>{label}</strong><br/>Type: {source_type}<br/>URL: <code>{url[:100]}...</code></li>'
            html += '</ul>'
            return mark_safe(html)
        return 'No video sources'
    video_sources_display.short_description = 'Video Sources'
    
    def download_links_display(self, obj):
        if obj.download_links:
            html = '<ul>'
            for i, link in enumerate(obj.download_links, 1):
                label = link.get('label', f'Download {i}')
                url = link.get('url', 'No URL')
                link_type = link.get('type', 'Unknown')
                html += f'<li><strong>{label}</strong><br/>Type: {link_type}<br/>URL: <code>{url[:100]}...</code></li>'
            html += '</ul>'
            return mark_safe(html)
        return 'No download links'
    download_links_display.short_description = 'Download Links'
    
    actions = ['mark_as_published', 'mark_as_draft', 'reset_view_count']
    
    def mark_as_published(self, request, queryset):
        updated = queryset.update(status='publish')
        self.message_user(request, f'{updated} movies marked as published.')
    mark_as_published.short_description = 'Mark selected movies as published'
    
    def mark_as_draft(self, request, queryset):
        updated = queryset.update(status='draft')
        self.message_user(request, f'{updated} movies marked as draft.')
    mark_as_draft.short_description = 'Mark selected movies as draft'
    
    def reset_view_count(self, request, queryset):
        updated = queryset.update(view_count=0)
        self.message_user(request, f'View count reset for {updated} movies.')
    reset_view_count.short_description = 'Reset view count'

@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'episode_count', 'created_at']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name', 'description']
    readonly_fields = ['created_at']
    
    def episode_count(self, obj):
        return obj.episodes.count()
    episode_count.short_description = 'Episodes'

@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = [
        'series', 
        'season_number', 
        'episode_number', 
        'movie_title',
        'movie_link'
    ]
    list_filter = ['series', 'season_number']
    search_fields = ['series__name', 'movie__title']
    ordering = ['series', 'season_number', 'episode_number']
    
    def movie_title(self, obj):
        return obj.movie.title[:50] + '...' if len(obj.movie.title) > 50 else obj.movie.title
    movie_title.short_description = 'Movie Title'
    
    def movie_link(self, obj):
        return format_html(
            '<a href="{}" target="_blank">View Movie</a>',
            obj.movie.get_absolute_url()
        )
    movie_link.short_description = 'Link'

# Customize admin site
admin.site.site_header = 'BangXXX Admin'
admin.site.site_title = 'BangXXX Admin Portal'
admin.site.index_title = 'Welcome to BangXXX Administration'

# Add custom CSS to admin
# admin.site.index_template = 'admin/custom_index.html'