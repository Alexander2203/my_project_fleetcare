from django.contrib import admin
from django.urls import path, include
from core.api import router as api_router

urlpatterns = [
    
    # Админка
    path("admin/", admin.site.urls),
    
    # Телега
    path("api/", include(api_router.urls)),
]
