from django.urls import path

from analytics.views import AnalysisView

urlpatterns = [
    path('analysis', AnalysisView.as_view(), name='analysis'),
]
