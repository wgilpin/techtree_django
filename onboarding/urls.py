"""URL configuration for the onboarding app."""

from django.urls import path
from . import views

# Define URL names for use in templates {% url '...' %}
# We are not using a namespace here, consistent with the 'core' app
urlpatterns = [

    # URL to display the assessment page for a given topic
    # Example: /onboarding/assess/Python%20Programming/
    path('assess/<str:topic>/', views.assessment_page_view, name='onboarding_assessment_page'),

    # URL to start a new assessment for a given topic
    # Example: /onboarding/start/Python%20Programming/
    path('start/<str:topic>/', views.start_assessment_view, name='onboarding_start'),

    # URL to submit an answer during an assessment
    # We might need a way to identify the specific assessment session (e.g., via Django session)
    path('submit/', views.submit_answer_view, name='onboarding_submit'),

    # URL to view the result of a completed assessment (if needed)
    # path('result/', views.assessment_result_view, name='onboarding_result'),

    # URL to handle skipping the assessment
    # pylint: disable=no-member
    path('skip/', views.skip_assessment_view, name='skip_assessment'),
]
