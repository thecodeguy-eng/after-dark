from django.db import models
from django.utils import timezone
from django.urls import reverse
import json

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Categories"

class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Movie(models.Model):
    # Basic fields matching JSON structure
    wp_id = models.IntegerField(unique=True, null=True, blank=True)  # WordPress ID
    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=500, unique=True)
    content = models.TextField(blank=True)
    excerpt = models.TextField(blank=True)
    
    # Dates from WordPress
    date = models.DateTimeField()
    date_gmt = models.DateTimeField()
    modified = models.DateTimeField()
    modified_gmt = models.DateTimeField()
    
    # Status and type
    status = models.CharField(max_length=50, default='publish')
    post_type = models.CharField(max_length=50, default='post')
    
    # Media
    featured_media_id = models.IntegerField(null=True, blank=True)
    image_url = models.URLField(blank=True)
    
    # Video sources - JSON field to store multiple sources
    video_sources = models.JSONField(default=list, blank=True)
    
    # Download links - JSON field to store multiple download options
    download_links = models.JSONField(default=list, blank=True)
    
    # Relationships
    categories = models.ManyToManyField(Category, blank=True)
    tags = models.ManyToManyField(Tag, blank=True)
    
    # Additional fields
    author_id = models.IntegerField(default=1)
    comment_status = models.CharField(max_length=20, default='open')
    ping_status = models.CharField(max_length=20, default='open')
    is_sticky = models.BooleanField(default=False)
    view_count = models.PositiveIntegerField(default=0)
    
    # SEO fields
    meta_description = models.TextField(blank=True)
    canonical_url = models.URLField(blank=True)
    
    # Internal fields
    scraped = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['slug']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('movies:movie_detail', kwargs={'slug': self.slug})

    def increment_view_count(self):
        self.view_count += 1
        self.save(update_fields=['view_count'])

    def get_primary_video_source(self):
        """Get the first video source or None"""
        if self.video_sources:
            return self.video_sources[0] if isinstance(self.video_sources, list) else None
        return None

    def get_primary_download_link(self):
        """Get the first download link or None"""
        if self.download_links:
            return self.download_links[0] if isinstance(self.download_links, list) else None
        return None

    @property
    def category_list(self):
        return list(self.categories.values_list('name', flat=True))

    @property
    def tag_list(self):
        return list(self.tags.values_list('name', flat=True))

class Series(models.Model):
    """Model to group related episodes/movies"""
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    image_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name_plural = "Series"

class Episode(models.Model):
    """Individual episodes within a series"""
    series = models.ForeignKey(Series, on_delete=models.CASCADE, related_name='episodes')
    movie = models.OneToOneField(Movie, on_delete=models.CASCADE)
    episode_number = models.PositiveIntegerField()
    season_number = models.PositiveIntegerField(default=1)
    
    class Meta:
        ordering = ['season_number', 'episode_number']
        unique_together = ['series', 'season_number', 'episode_number']
    
    def __str__(self):
        return f"{self.series.name} S{self.season_number:02d}E{self.episode_number:02d}"