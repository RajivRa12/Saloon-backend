from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('apps.authentication.urls')),
    path('api/v1/', include('apps.master_admin.urls')),
    path('api/master/', include('apps.master_admin.urls')),
    path('api/erp/', include('apps.store_erp.urls')),
    path('api/customer/', include('apps.customers.urls')),
    path('api/staff/', include('apps.staff.urls')),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
